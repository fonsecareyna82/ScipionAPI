from pathlib import Path
from typing import Dict, List, Tuple, Optional
import os
import re


_ENV_KEY_RE = re.compile(r"^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=")


def _parseEnvLine(line: str) -> Optional[Tuple[str, str]]:
    # Parse a dotenv assignment while ignoring comments and malformed lines.
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        return None

    match = _ENV_KEY_RE.match(stripped)
    if not match:
        return None

    key = match.group(1).strip()
    rawValue = stripped[match.end():].strip()
    value = _parseEnvValue(rawValue)
    return key, value


def _parseEnvValue(rawValue: str) -> str:
    # Parse a simple dotenv value with optional single/double quotes.
    value = rawValue.strip()

    if not value:
        return ""

    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        quote = value[0]
        inner = value[1:-1]
        if quote == '"':
            return (
                inner
                .replace("\\n", "\n")
                .replace("\\r", "\r")
                .replace("\\t", "\t")
                .replace('\\"', '"')
                .replace("\\\\", "\\")
            )
        return inner.replace("\\'", "'").replace("\\\\", "\\")

    return _stripInlineComment(value).strip()


def _stripInlineComment(value: str) -> str:
    # Strip comments only when # starts a shell-like comment.
    inSingle = False
    inDouble = False
    escaped = False

    for index, char in enumerate(value):
        if escaped:
            escaped = False
            continue

        if char == "\\":
            escaped = True
            continue

        if char == "'" and not inDouble:
            inSingle = not inSingle
            continue

        if char == '"' and not inSingle:
            inDouble = not inDouble
            continue

        if char == "#" and not inSingle and not inDouble:
            if index == 0 or value[index - 1].isspace():
                return value[:index]

    return value


def _formatEnvValue(value: str) -> str:
    # Keep simple values unquoted and quote only when needed.
    text = "" if value is None else str(value)

    if text == "":
        return '""'

    needsQuote = any(char.isspace() for char in text) or "#" in text or '"' in text or "'" in text

    if not needsQuote:
        return text

    escaped = (
        text
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )
    return f'"{escaped}"'


def _iterExistingLines(envPath: Path) -> List[str]:
    if not envPath.exists():
        return []
    return envPath.read_text(encoding="utf-8").splitlines()


def readEnvFile(envPath: Path) -> Dict[str, str]:
    # Read a dotenv file into a dictionary.
    data: Dict[str, str] = {}

    for line in _iterExistingLines(envPath):
        parsed = _parseEnvLine(line)
        if parsed is None:
            continue

        key, value = parsed
        data[key] = value

    return data


def writeEnvFile(envPath: Path, updates: Dict[str, str]) -> None:
    # Merge updates into a dotenv file while preserving comments and key order.
    envPath.parent.mkdir(parents=True, exist_ok=True)

    normalizedUpdates = {
        str(key): str(value)
        for key, value in updates.items()
        if value is not None
    }

    existingLines = _iterExistingLines(envPath)
    writtenKeys = set()
    outputLines: List[str] = []

    for line in existingLines:
        parsed = _parseEnvLine(line)
        if parsed is None:
            outputLines.append(line)
            continue

        key, _ = parsed
        if key not in normalizedUpdates:
            outputLines.append(line)
            continue

        outputLines.append(f"{key}={_formatEnvValue(normalizedUpdates[key])}")
        writtenKeys.add(key)

    for key in sorted(normalizedUpdates.keys()):
        if key in writtenKeys:
            continue
        outputLines.append(f"{key}={_formatEnvValue(normalizedUpdates[key])}")

    outputLines.append("")
    envPath.write_text("\n".join(outputLines), encoding="utf-8")

    try:
        envPath.chmod(0o600)
    except Exception:
        pass


def exportEnvToOs(envPath: Path, overrideExisting: bool = True) -> None:
    # Export dotenv values to the current process environment.
    current = readEnvFile(envPath)

    for key, value in current.items():
        if value is None:
            continue

        if overrideExisting or key not in os.environ:
            os.environ[key] = value