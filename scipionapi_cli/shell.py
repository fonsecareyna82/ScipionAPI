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
) -> subprocess.CompletedProcess:
    # runCommandHelper
    mergedEnv = os.environ.copy()
    if env:
        mergedEnv.update(env)

    return subprocess.run(
        args,
        cwd=str(cwd) if cwd else None,
        env=mergedEnv,
        text=True,
        capture_output=capture,
    )
