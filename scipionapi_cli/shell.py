import os
import subprocess
from pathlib import Path
from typing import Optional, Dict, List


def resolveRepoRoot() -> Path:
    # resolveRepoRootByMarkers
    current = Path.cwd().resolve()
    for parent in [current, *current.parents]:
        if (parent / "alembic.ini").exists() and (parent / "app").exists():
            return parent
    return current


def runCmd(
    args: List[str],
    cwd: Optional[Path] = None,
    env: Optional[Dict[str, str]] = None,
    capture: bool = False,
    live: bool = False,
) -> subprocess.CompletedProcess:
    # runCommandHelper
    if capture and live:
        raise ValueError("runCmd does not support capture=True and live=True at the same time.")

    mergedEnv = os.environ.copy()
    if env:
        mergedEnv.update(env)

    if live:
        proc = subprocess.Popen(
            args,
            cwd=str(cwd) if cwd else None,
            env=mergedEnv,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1,
        )

        lines: List[str] = []

        assert proc.stdout is not None
        for line in proc.stdout:
            print(line, end="", flush=True)
            lines.append(line)

        proc.wait()

        return subprocess.CompletedProcess(
            args=args,
            returncode=proc.returncode,
            stdout="".join(lines),
            stderr="",
        )

    return subprocess.run(
        args,
        cwd=str(cwd) if cwd else None,
        env=mergedEnv,
        text=True,
        capture_output=capture,
    )