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
import os
import subprocess
from pathlib import Path
from typing import Dict, Iterable, List, Optional


def _isRepoRoot(path: Path) -> bool:
    # Check whether a path looks like the ScipionAPI repository root.
    return (
        (path / "alembic.ini").exists()
        and (path / "app").exists()
        and (path / "pyproject.toml").exists()
    )


def _walkParents(path: Path) -> Iterable[Path]:
    # Yield path and all parents.
    yield path
    for parent in path.parents:
        yield parent


def resolveRepoRoot() -> Path:
    # Resolve repository root from cwd first, then from this file location.
    candidates = []

    try:
        candidates.append(Path.cwd().resolve())
    except Exception:
        pass

    try:
        candidates.append(Path(__file__).resolve())
    except Exception:
        pass

    for candidate in candidates:
        start = candidate if candidate.is_dir() else candidate.parent

        for parent in _walkParents(start):
            if _isRepoRoot(parent):
                return parent

    fallback = Path.cwd().resolve()
    return fallback


def formatCommand(args: List[str]) -> str:
    # Format a command for readable logs without using shell=True.
    return " ".join(str(arg) for arg in args)


def _normalizeOutput(value: object) -> str:
    # Convert subprocess timeout output to text safely.
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def runCmd(
    args: List[str],
    cwd: Optional[Path] = None,
    env: Optional[Dict[str, str]] = None,
    capture: bool = False,
    live: bool = False,
    timeout: Optional[float] = None,
) -> subprocess.CompletedProcess:
    # Run a subprocess command with optional captured or live output.
    if capture and live:
        raise ValueError("runCmd does not support capture=True and live=True at the same time.")

    if not args:
        raise ValueError("runCmd requires at least one command argument.")

    mergedEnv = os.environ.copy()
    if env:
        mergedEnv.update(env)

    cwdText = str(cwd) if cwd else None

    if live:
        proc = subprocess.Popen(
            args,
            cwd=cwdText,
            env=mergedEnv,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1,
        )

        lines: List[str] = []

        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                print(line, end="", flush=True)
                lines.append(line)

            proc.wait(timeout=timeout)

        except subprocess.TimeoutExpired:
            try:
                proc.kill()
            except Exception:
                pass

            stdout = "".join(lines)
            return subprocess.CompletedProcess(
                args=args,
                returncode=124,
                stdout=stdout,
                stderr=f"Command timed out after {timeout} seconds: {formatCommand(args)}",
            )

        return subprocess.CompletedProcess(
            args=args,
            returncode=proc.returncode,
            stdout="".join(lines),
            stderr="",
        )

    try:
        return subprocess.run(
            args,
            cwd=cwdText,
            env=mergedEnv,
            text=True,
            capture_output=capture,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = _normalizeOutput(exc.stdout)
        stderr = _normalizeOutput(exc.stderr)
        timeoutMessage = f"Command timed out after {timeout} seconds: {formatCommand(args)}"
        stderr = f"{stderr}\n{timeoutMessage}".strip()

        return subprocess.CompletedProcess(
            args=args,
            returncode=124,
            stdout=stdout,
            stderr=stderr,
        )
