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

import os
import re
import subprocess
from pathlib import Path
from shutil import which
from typing import List, Optional
import shlex

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


def _run(cmd: List[str], cwd: Optional[Path] = None) -> None:
    # runCommandOrFail
    proc = subprocess.run(cmd, cwd=str(cwd) if cwd else None, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"Command failed ({proc.returncode}): {' '.join(cmd)}")


def _runCapture(cmd: List[str], cwd: Optional[Path] = None) -> subprocess.CompletedProcess:
    # runCommandCapture
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
    )

def _envInt(name: str, default: int) -> int:
    # readIntEnv
    try:
        return int((os.getenv(name) or "").strip() or default)
    except Exception:
        return default


def _envFlag(name: str, default: bool = False) -> bool:
    # readBoolEnv
    raw = (os.getenv(name) or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _splitPackageList(value: str) -> List[str]:
    # splitPackageListShellLike
    try:
        return [item for item in shlex.split(value or "") if item.strip()]
    except Exception:
        return [item for item in (value or "").split(" ") if item.strip()]


def _resolveCondaExe() -> str:
    # resolveCondaExeFromEnvOrPath
    candidates = [
        (os.getenv("SCIPIONAPI_CONDA_EXE") or "").strip(),
        (os.getenv("CONDA_EXE") or "").strip(),
        which("conda") or "",
    ]

    for candidate in candidates:
        if not candidate:
            continue

        try:
            proc = _runCapture([candidate, "--version"])
        except Exception:
            continue

        if proc.returncode == 0:
            return candidate

    raise RuntimeError(
        "conda is required but was not found in PATH "
        "(or SCIPIONAPI_CONDA_EXE/CONDA_EXE is invalid)."
    )


def _condaEnvExists(condaExe: str, envName: str) -> bool:
    # condaEnvExists
    proc = _runCapture([condaExe, "env", "list"])
    if proc.returncode != 0:
        return False

    for line in (proc.stdout or "").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        name = s.split()[0].strip()
        if name == envName:
            return True

    return False


def _condaEnvHealthy(condaExe: str, envName: str) -> bool:
    # condaEnvHealthy
    pythonCheck = _runCapture(
        [condaExe, "run", "-n", envName, "python", "--version"]
    )
    if pythonCheck.returncode != 0:
        return False

    pipCheck = _runCapture(
        [condaExe, "run", "-n", envName, "python", "-m", "pip", "--version"]
    )
    return pipCheck.returncode == 0


_MIN_JAVA_VERSION = 21
_DEFAULT_JAVA_PACKAGE = "openjdk=21"


def _parseJavaMajorVersion(output: str) -> Optional[int]:
    # parseJavaMajorVersion
    match = re.search(r'version\s+"([^"]+)"', output or "")
    if not match:
        return None

    version = match.group(1)
    parts = version.split(".")

    try:
        if parts[0] == "1" and len(parts) > 1:
            return int(parts[1])

        return int(re.split(r"[^0-9]", parts[0])[0])
    except Exception:
        return None


def _getJavaMajorVersion(condaExe: str, envName: str) -> Optional[int]:
    # getJavaMajorVersion
    proc = _runCapture([
        condaExe,
        "run",
        "-n",
        envName,
        "java",
        "-version",
    ])

    if proc.returncode != 0:
        return None

    output = f"{proc.stdout or ''}\n{proc.stderr or ''}"
    return _parseJavaMajorVersion(output)


def _ensureJavaRuntime(condaExe: str, envName: str) -> int:
    # ensureJavaRuntime
    javaVersion = _getJavaMajorVersion(condaExe, envName)

    if javaVersion is not None and javaVersion >= _MIN_JAVA_VERSION:
        return javaVersion

    javaPackage = (
        os.getenv("SCIPIONAPI_JAVA_PACKAGE")
        or _DEFAULT_JAVA_PACKAGE
    ).strip()

    if javaVersion is None:
        _printInfo(f"Java runtime not found; installing {javaPackage}")
    else:
        _printInfo(
            f"Java {javaVersion} detected; "
            f"Java {_MIN_JAVA_VERSION}+ is required. Installing {javaPackage}"
        )

    _run([
        condaExe,
        "install",
        "-y",
        "-n",
        envName,
        "-c",
        "conda-forge",
        javaPackage,
    ])

    javaVersion = _getJavaMajorVersion(condaExe, envName)

    if javaVersion is None or javaVersion < _MIN_JAVA_VERSION:
        raise RuntimeError(
            f"Java {_MIN_JAVA_VERSION}+ is required but the runtime "
            f"could not be prepared correctly in conda env '{envName}'."
        )

    return javaVersion


def _removeCondaEnv(condaExe: str, envName: str) -> None:
    # removeCondaEnv
    _run([condaExe, "env", "remove", "-n", envName, "-y"])


def _pip(condaExe: str, envName: str, args: List[str], cwd: Path) -> None:
    # runPipInCondaEnvWithLiveOutput
    pipRetries = _envInt("SCIPIONAPI_PIP_RETRIES", 10)
    pipTimeout = _envInt("SCIPIONAPI_PIP_TIMEOUT", 120)
    pipVerbose = _envFlag("SCIPIONAPI_PIP_VERBOSE", False)

    pipArgs = [
        "install",
        "--progress-bar",
        "on",
        "--retries",
        str(pipRetries),
        "--timeout",
        str(pipTimeout),
    ]

    if pipVerbose:
        pipArgs.append("-v")

    forwardedArgs = list(args)
    if forwardedArgs and forwardedArgs[0] == "install":
        forwardedArgs = forwardedArgs[1:]

    cmd = [
        condaExe,
        "run",
        "--live-stream",
        "-n",
        envName,
        "python",
        "-m",
        "pip",
    ] + pipArgs + forwardedArgs

    _run(cmd, cwd=cwd)


def _pythonImportOk(condaExe: str, envName: str, moduleName: str) -> bool:
    # pythonImportOk
    proc = _runCapture(
        [condaExe, "run", "-n", envName, "python", "-c", f"import {moduleName}"]
    )
    return proc.returncode == 0


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


def _printSummaryTable(
    repoRoot: Path,
    condaExe: str,
    envName: str,
    pythonVersion: str,
    installScipionCore: bool,
    scipionCorePackages: str,
    recreateEnv: bool,
) -> None:
    # printSummaryTable
    if _HAS_RICH:
        table = Table(title="Bootstrap configuration", header_style="bold magenta")
        table.add_column("Field", style="bold white", no_wrap=True)
        table.add_column("Value", style="white")

        table.add_row("Repo root", str(repoRoot))
        table.add_row("Conda executable", condaExe)
        table.add_row("Target env", envName)
        table.add_row("Python version", pythonVersion)
        table.add_row("Recreate env", "yes" if recreateEnv else "no")
        table.add_row("Install Scipion core", "yes" if installScipionCore else "no")
        table.add_row("Scipion core packages", scipionCorePackages)

        _console.print(table)
    else:
        print("Bootstrap configuration:", flush=True)
        print(f"  Repo root: {repoRoot}", flush=True)
        print(f"  Conda executable: {condaExe}", flush=True)
        print(f"  Target env: {envName}", flush=True)
        print(f"  Python version: {pythonVersion}", flush=True)
        print(f"  Recreate env: {'yes' if recreateEnv else 'no'}", flush=True)
        print(f"  Install Scipion core: {'yes' if installScipionCore else 'no'}", flush=True)
        print(f"  Scipion core packages: {scipionCorePackages}", flush=True)


def bootstrapCommand(
    envName: str,
    pythonVersion: str,
    installScipionCore: bool,
    scipionCorePackages: str,
) -> None:
    # bootstrapCommand
    repoRoot = resolveRepoRoot()
    condaExe = _resolveCondaExe()
    recreateEnv = (os.getenv("SCIPIONAPI_BOOTSTRAP_RECREATE") or "").strip() == "1"

    _printPanel(
        "ScipionAPI bootstrap",
        "This command prepares the Python/Conda environment and installs package dependencies.",
    )
    _printSummaryTable(
        repoRoot=repoRoot,
        condaExe=condaExe,
        envName=envName,
        pythonVersion=pythonVersion,
        installScipionCore=installScipionCore,
        scipionCorePackages=scipionCorePackages,
        recreateEnv=recreateEnv,
    )

    _printStep("Checking conda environment", envName)
    envExists = _condaEnvExists(condaExe, envName)

    if envExists and recreateEnv:
        _printWarning(f"Recreate requested, removing conda env '{envName}'")
        _removeCondaEnv(condaExe, envName)
        envExists = False
        _printSuccess(f"Conda env removed: {envName}")

    if envExists:
        _printInfo(f"Validating existing conda env '{envName}'")
        if not _condaEnvHealthy(condaExe, envName):
            raise RuntimeError(
                f"Conda env '{envName}' exists but looks unhealthy.\n"
                f"Re-run with SCIPIONAPI_BOOTSTRAP_RECREATE=1 to recreate it."
            )
        _printSuccess(f"Conda env already exists and looks healthy: {envName}")
    else:
        _printInfo(f"Creating conda env '{envName}' with python={pythonVersion}")
        _run([condaExe, "create", "-y", "-n", envName, f"python={pythonVersion}"])
        _printSuccess(f"Conda env created: {envName}")

    _printStep("Checking Java runtime", envName)
    javaVersion = _ensureJavaRuntime(condaExe, envName)
    _printSuccess(f"Java {javaVersion} runtime ready")

    _printStep("Upgrading pip", envName)
    _pip(
        condaExe,
        envName,
        ["install", "--upgrade", "pip"],
        cwd=repoRoot,
    )
    _printSuccess("pip upgrade completed")

    _printStep("Installing ScipionAPI and dependencies", str(repoRoot))
    _pip(
        condaExe,
        envName,
        ["install", "-e", str(repoRoot)],
        cwd=repoRoot,
    )
    _printSuccess("ScipionAPI package installation completed")

    _printStep("Checking Scipion core packages")
    if installScipionCore:
        if not _pythonImportOk(condaExe, envName, "pyworkflow"):
            _printInfo(f"Installing Scipion core packages: {scipionCorePackages}")
            packages = _splitPackageList(scipionCorePackages)
            _pip(
                condaExe,
                envName,
                ["install"] + packages,
                cwd=repoRoot,
            )

            if not _pythonImportOk(condaExe, envName, "pyworkflow"):
                raise RuntimeError(
                    "pyworkflow import still failing after installing Scipion core packages."
                )

            _printSuccess("Scipion core packages installed correctly")
        else:
            _printSuccess("Scipion core packages already available")
    else:
        _printWarning("Skipping Scipion core package installation")

    _printPanel("Bootstrap completed", f"Environment ready: {envName}")