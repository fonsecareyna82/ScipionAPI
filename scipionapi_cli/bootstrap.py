from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Optional

from scipionapi_cli.shell import resolveRepoRoot
from scipionapi_cli.install import installCommand
from scipionapi_cli.runtime import startCommand


def _run(cmd: list[str], cwd: Optional[Path] = None) -> None:
    # runCommandOrFail
    proc = subprocess.run(cmd, cwd=str(cwd) if cwd else None)
    if proc.returncode != 0:
        raise RuntimeError(f"Command failed ({proc.returncode}): {' '.join(cmd)}")


def _runCapture(cmd: list[str], cwd: Optional[Path] = None) -> subprocess.CompletedProcess:
    # runCommandCapture
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
    )


def _requireConda() -> str:
    # requireCondaInPath
    condaExe = (os.getenv("CONDA_EXE") or "conda").strip()
    proc = _runCapture([condaExe, "--version"])
    if proc.returncode != 0:
        raise RuntimeError("conda is required but was not found in PATH (or CONDA_EXE is invalid).")
    return condaExe


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


def _pip(condaExe: str, envName: str, args: list[str], cwd: Path) -> None:
    # runPipInCondaEnv
    _run([condaExe, "run", "-n", envName, "python", "-m", "pip"] + args, cwd=cwd)


def _pythonImportOk(condaExe: str, envName: str, moduleName: str) -> bool:
    # pythonImportOk
    proc = _runCapture([condaExe, "run", "-n", envName, "python", "-c", f"import {moduleName}"])
    return proc.returncode == 0


def bootstrapCommand(
    envName: str,
    pythonVersion: str,
    installScipionCore: bool,
    scipionCorePackages: str,
) -> None:
    # bootstrapCommand
    repoRoot = resolveRepoRoot()
    condaExe = _requireConda()

    if not _condaEnvExists(condaExe, envName):
        print(f"Creating conda env: {envName} (python={pythonVersion})")
        _run([condaExe, "create", "-y", "-n", envName, f"python={pythonVersion}"])

    print("Upgrading pip")
    _pip(condaExe, envName, ["install", "--upgrade", "pip"], cwd=repoRoot)

    reqPath = repoRoot / "requirements.txt"
    if reqPath.exists():
        print("Installing requirements.txt")
        _pip(condaExe, envName, ["install", "-r", str(reqPath)], cwd=repoRoot)

    if installScipionCore:
        if not _pythonImportOk(condaExe, envName, "pyworkflow"):
            print("Installing Scipion core packages (pyworkflow/em/app/tomo)")
            packages = [p for p in scipionCorePackages.split(" ") if p.strip()]
            _pip(condaExe, envName, ["install"] + packages, cwd=repoRoot)

            if not _pythonImportOk(condaExe, envName, "pyworkflow"):
                raise RuntimeError("pyworkflow import still failing after installing Scipion core packages.")

    print("Installing package (editable)")
    _pip(condaExe, envName, ["install", "-e", str(repoRoot)], cwd=repoRoot)

    print("Bootstrap completed.")


def provisionCommand(
    adminUser: str,
    adminEmail: str,
    adminPassword: str,
    envName: str,
    pythonVersion: str,
    installScipionCore: bool,
    scipionCorePackages: str,
    runBootstrap: bool,
) -> None:
    # provisionCommand
    if runBootstrap:
        bootstrapCommand(
            envName=envName,
            pythonVersion=pythonVersion,
            installScipionCore=installScipionCore,
            scipionCorePackages=scipionCorePackages,
        )

    installCommand(adminUser=adminUser, adminEmail=adminEmail, adminPassword=adminPassword)
    startCommand()

    print("Provision completed.")
