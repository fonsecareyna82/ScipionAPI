"""Where the thumbnail of an output lives: one file per output, size and signature.

``<project>/.thumbnail_cache/v3/p<protocolId>/<output>_<size>_<signature>.webp``,
next to a ``.missing`` file when the output cannot be drawn. Finding out whether
a thumbnail exists is a file check: no project to load, no lock.
"""
from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import Optional

CACHE_FOLDER = ".thumbnail_cache"
CACHE_LAYOUT = "v3"
IMAGE_SUFFIX = ".webp"
MISSING_SUFFIX = ".missing"

# Thumbnails are drawn at these widths; a request takes the next one up so
# that cards and nodes of similar sizes share files.
SIZES = (192, 256, 384, 512, 768, 1024)


def snapSize(size: int) -> int:
    for candidate in SIZES:
        if int(size) <= candidate:
            return candidate
    return SIZES[-1]


def _token(outputName: str) -> str:
    raw = str(outputName or "")
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", raw).strip("._") or "output"
    return f"{safe[:60]}-{hashlib.sha1(raw.encode('utf-8')).hexdigest()[:8]}"


def protocolFolder(projectPath: str, protocolId: str) -> Path:
    safeProtocol = re.sub(r"[^A-Za-z0-9_-]+", "_", str(protocolId))
    return Path(projectPath) / CACHE_FOLDER / CACHE_LAYOUT / f"p{safeProtocol}"


def thumbnailPath(projectPath: str, protocolId: str, outputName: str, size: int, signature: str) -> Path:
    return protocolFolder(projectPath, protocolId) / f"{_token(outputName)}_{int(size)}_{signature}{IMAGE_SUFFIX}"


def missingPath(imagePath: Path) -> Path:
    return imagePath.with_suffix(MISSING_SUFFIX)


def isReady(imagePath: Path) -> bool:
    try:
        return imagePath.stat().st_size > 0
    except OSError:
        return False


def isMissing(imagePath: Path) -> bool:
    return missingPath(imagePath).exists()


def writeImage(imagePath: Path, data: bytes) -> None:
    """Store the image atomically and drop the older signatures of the same output and size."""
    imagePath.parent.mkdir(parents=True, exist_ok=True)
    temporary = imagePath.with_name(f".{imagePath.name}.{os.getpid()}.tmp")
    temporary.write_bytes(data)
    os.replace(temporary, imagePath)
    missingPath(imagePath).unlink(missing_ok=True)
    _dropOtherSignatures(imagePath)


def writeMissing(imagePath: Path, reason: str) -> None:
    imagePath.parent.mkdir(parents=True, exist_ok=True)
    missingPath(imagePath).write_text(str(reason or "Thumbnail not available"), encoding="utf-8")
    imagePath.unlink(missing_ok=True)
    _dropOtherSignatures(imagePath)


def _dropOtherSignatures(imagePath: Path) -> None:
    prefix = imagePath.name.rsplit("_", 1)[0] + "_"
    try:
        for sibling in imagePath.parent.iterdir():
            if (sibling.name.startswith(prefix) and sibling.stem != imagePath.stem
                    and sibling.suffix in (IMAGE_SUFFIX, MISSING_SUFFIX)):
                sibling.unlink(missing_ok=True)
    except OSError:
        pass


def readMissingReason(imagePath: Path) -> Optional[str]:
    try:
        return missingPath(imagePath).read_text(encoding="utf-8")
    except OSError:
        return None
