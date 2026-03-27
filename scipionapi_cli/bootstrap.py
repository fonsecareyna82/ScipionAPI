from __future__ import annotations

import os
import subprocess
from pathlib import Path
from shutil import which
from typing import List, Optional

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
    proc = subprocess.run(cmd, cwd=str(cwd) if cwd else None)
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


def _resolveCondaExe() -> str:
    # resolveCondaExeFromEnvOrPath
    candidates = [
        (os.getenv("SCIPIONAPI_CONDA_EXE") or "").strip(),
        (os.getenv("CONDA_EXE") or "").strip(),
        which("conda") or "",
    ]
    for candidate in candidates:
        if candidate:
            proc = _runCapture([candidate, "--version"])
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


def _pip(condaExe: str, envName: str, args: List[str], cwd: Path) -> None:
    # runPipInCondaEnvWithLiveOutput
    cmd = [
        condaExe,
        "run",
        "--live-stream",
        "-n",
        envName,
        "python",
        "-m",
        "pip",
    ] + args
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
        table.add_row("Install Scipion core", "yes" if installScipionCore else "no")
        table.add_row("Scipion core packages", scipionCorePackages)

        _console.print(table)
    else:
        print("Bootstrap configuration:", flush=True)
        print(f"  Repo root: {repoRoot}", flush=True)
        print(f"  Conda executable: {condaExe}", flush=True)
        print(f"  Target env: {envName}", flush=True)
        print(f"  Python version: {pythonVersion}", flush=True)
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

    _printPanel("ScipionAPI bootstrap")
    _printSummaryTable(
        repoRoot=repoRoot,
        condaExe=condaExe,
        envName=envName,
        pythonVersion=pythonVersion,
        installScipionCore=installScipionCore,
        scipionCorePackages=scipionCorePackages,
    )

    _printStep("Checking conda environment", envName)
    if not _condaEnvExists(condaExe, envName):
        _printInfo(f"Creating conda env '{envName}' with python={pythonVersion}")
        _run([condaExe, "create", "-y", "-n", envName, f"python={pythonVersion}"])
        _printSuccess(f"Conda env created: {envName}")
    else:
        _printSuccess(f"Conda env already exists: {envName}")

    _printStep("Upgrading pip", envName)
    _pip(
        condaExe,
        envName,
        ["install", "--upgrade", "pip", "--progress-bar", "on"],
        cwd=repoRoot,
    )
    _printSuccess("pip upgrade completed")

    reqPath = repoRoot / "requirements.txt"
    _printStep("Installing requirements", str(reqPath))
    if reqPath.exists():
        _printInfo("Streaming pip output live")
        _pip(
            condaExe,
            envName,
            ["install", "-r", str(reqPath), "--progress-bar", "on"],
            cwd=repoRoot,
        )
        _printSuccess("requirements.txt installation completed")
    else:
        _printWarning("requirements.txt not found, skipping requirements installation")

    _printStep("Checking Scipion core packages")
    if installScipionCore:
        if not _pythonImportOk(condaExe, envName, "pyworkflow"):
            _printInfo(f"Installing Scipion core packages: {scipionCorePackages}")
            packages = [p for p in scipionCorePackages.split(" ") if p.strip()]
            _pip(
                condaExe,
                envName,
                ["install", "--progress-bar", "on"] + packages,
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

    _printStep("Installing package in editable mode", str(repoRoot))
    _pip(
        condaExe,
        envName,
        ["install", "-e", str(repoRoot), "--progress-bar", "on"],
        cwd=repoRoot,
    )
    _printSuccess("Editable package installation completed")

    _printPanel("Bootstrap completed", f"Environment ready: {envName}")