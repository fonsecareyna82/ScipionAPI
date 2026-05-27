#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


VERSION_RE = re.compile(r"^v?[0-9]+(?:\.[0-9]+){1,3}(?:[-._A-Za-z0-9]*)?$")


def normalizeVersion(value: str) -> str:
    # Normalize release versions to the public tag format used by downloads.
    version = (value or "").strip()
    if not version:
        raise ValueError("Version is required.")

    if not VERSION_RE.match(version):
        raise ValueError(
            "Invalid version format. Expected values like v4.0.0 or 4.0.0."
        )

    if version.startswith("v"):
        return version

    return f"v{version}"


def readManifest(manifestPath: Path) -> Dict[str, Any]:
    # Read an existing manifest or return an empty structure.
    if not manifestPath.exists():
        return {"latest": "", "releases": {}}

    with manifestPath.open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    if not isinstance(data, dict):
        raise ValueError(f"Manifest must be a JSON object: {manifestPath}")

    releases = data.get("releases")
    if not isinstance(releases, dict):
        data["releases"] = {}

    if "latest" not in data:
        data["latest"] = ""

    return data


def fileSha256(path: Path) -> str:
    # Calculate a file SHA256 digest in chunks.
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fileEntry(path: Path) -> Dict[str, Any]:
    # Build the manifest entry for a release asset.
    if not path.exists():
        raise FileNotFoundError(f"Release asset not found: {path}")

    if not path.is_file():
        raise ValueError(f"Release asset is not a file: {path}")

    return {
        "file": path.name,
        "sha256": fileSha256(path),
        "size": path.stat().st_size,
    }


def resolveAssetPath(downloadsDir: Path, fileName: Optional[str], defaultName: str) -> Path:
    # Resolve an asset path from either a custom file name or the default convention.
    candidate = Path(fileName) if fileName else Path(defaultName)

    if candidate.is_absolute():
        return candidate

    return downloadsDir / candidate


def writeManifest(manifestPath: Path, manifest: Dict[str, Any]) -> None:
    # Write a stable, human-readable manifest.
    manifestPath.parent.mkdir(parents=True, exist_ok=True)
    with manifestPath.open("w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, ensure_ascii=False, sort_keys=True)
        handle.write("\n")


def updateManifest(
    downloadsDir: Path,
    version: str,
    manifestPath: Optional[Path] = None,
    apiFile: Optional[str] = None,
    webFile: Optional[str] = None,
    setLatest: bool = True,
) -> Tuple[Path, Dict[str, Any]]:
    # Update manifest.json for one ScipionAPI/ScipionWeb paired release.
    normalizedVersion = normalizeVersion(version)
    downloadsDir = downloadsDir.expanduser().resolve()

    if manifestPath is None:
        manifestPath = downloadsDir / "manifest.json"
    else:
        manifestPath = manifestPath.expanduser().resolve()

    defaultApiName = f"ScipionAPI-{normalizedVersion}.zip"
    defaultWebName = f"ScipionWeb-{normalizedVersion}-dist.zip"

    apiPath = resolveAssetPath(downloadsDir, apiFile, defaultApiName)
    webPath = resolveAssetPath(downloadsDir, webFile, defaultWebName)

    manifest = readManifest(manifestPath)
    releases = manifest.setdefault("releases", {})

    generatedAt = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    releases[normalizedVersion] = {
        "api": fileEntry(apiPath),
        "web": fileEntry(webPath),
        "generatedAt": generatedAt,
    }

    if setLatest:
        manifest["latest"] = normalizedVersion

    manifest["generatedAt"] = generatedAt
    writeManifest(manifestPath, manifest)

    return manifestPath, manifest


def buildParser() -> argparse.ArgumentParser:
    # Build command-line parser.
    parser = argparse.ArgumentParser(
        description=(
            "Generate or update the ScipionWeb release manifest used by "
            "`scipionapi update`."
        )
    )
    parser.add_argument(
        "--version",
        required=True,
        help="Release version to add, for example v4.0.0 or 4.0.0.",
    )
    parser.add_argument(
        "--downloads-dir",
        required=True,
        help="Directory containing the ScipionAPI and ScipionWeb release ZIPs.",
    )
    parser.add_argument(
        "--manifest",
        default=None,
        help="Path to manifest.json. Defaults to <downloads-dir>/manifest.json.",
    )
    parser.add_argument(
        "--api-file",
        default=None,
        help="Custom API ZIP filename or path. Defaults to ScipionAPI-<version>.zip.",
    )
    parser.add_argument(
        "--web-file",
        default=None,
        help="Custom Web dist ZIP filename or path. Defaults to ScipionWeb-<version>-dist.zip.",
    )
    parser.add_argument(
        "--no-latest",
        action="store_true",
        help="Add/update the release without changing the manifest latest field.",
    )
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    # Command entry point.
    parser = buildParser()
    args = parser.parse_args(argv)

    try:
        manifestPath, manifest = updateManifest(
            downloadsDir=Path(args.downloads_dir),
            version=args.version,
            manifestPath=Path(args.manifest) if args.manifest else None,
            apiFile=args.api_file,
            webFile=args.web_file,
            setLatest=not args.no_latest,
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    latest = manifest.get("latest", "")
    print(f"Manifest updated: {manifestPath}")
    print(f"Latest: {latest}")
    print(f"Release: {normalizeVersion(args.version)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
