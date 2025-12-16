from pathlib import Path
from typing import Dict
import os


def readEnvFile(envPath: Path) -> Dict[str, str]:
    # readDotEnvFile
    data: Dict[str, str] = {}
    if not envPath.exists():
        return data
    for line in envPath.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        data[k.strip()] = v.strip()
    return data


def writeEnvFile(envPath: Path, updates: Dict[str, str]) -> None:
    # writeDotEnvFileMerge
    current = readEnvFile(envPath)
    current.update({k: v for k, v in updates.items() if v is not None})

    lines = [f"{k}={current[k]}" for k in sorted(current.keys())]
    lines.append("")
    envPath.write_text("\n".join(lines), encoding="utf-8")


def exportEnvToOs(envPath: Path, overrideExisting: bool = True) -> None:
    # exportDotEnvToOs
    current = readEnvFile(envPath)
    for k, v in current.items():
        if v is None:
            continue
        if overrideExisting or (k not in os.environ):
            os.environ[k] = v
