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

# systemRouter
import json
import os
import re
from typing import Any, Dict, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from fastapi import APIRouter, status

from scipionapi_cli.version import SCIPIONAPI_RELEASE_TAG


DEFAULT_UPDATE_BASE_URL = "https://scipion.cnb.csic.es/downloads/scipion/scipionWeb/"
DEFAULT_MANIFEST_NAME = "manifest.json"

router = APIRouter(prefix="/system", tags=["system"])


def _normalizeBaseUrl(value: Optional[str]) -> str:
    # normalizeBaseUrl
    baseUrl = (value or DEFAULT_UPDATE_BASE_URL).strip()
    if not baseUrl:
        baseUrl = DEFAULT_UPDATE_BASE_URL
    if not baseUrl.endswith("/"):
        baseUrl = f"{baseUrl}/"
    return baseUrl


def _normalizeVersionTag(value: Optional[str]) -> str:
    # normalizeVersionTag
    version = (value or "").strip()
    if not version:
        return "unknown"
    if version.lower() == "latest":
        return "latest"
    if re.match(r"^[0-9]+(?:\.[0-9]+){1,3}(?:[-._A-Za-z0-9]*)?$", version):
        return f"v{version}"
    return version


def _versionSortKey(version: str) -> Tuple[int, int, int, int, str]:
    # versionSortKey
    normalized = _normalizeVersionTag(version)
    match = re.match(
        r"^v?([0-9]+)(?:\.([0-9]+))?(?:\.([0-9]+))?(?:\.([0-9]+))?(.*)$",
        normalized,
    )
    if not match:
        return (0, 0, 0, 0, normalized)

    parts = []
    for index in range(1, 5):
        token = match.group(index)
        parts.append(int(token) if token is not None else 0)

    return (parts[0], parts[1], parts[2], parts[3], match.group(5) or "")


def _isNewerVersion(candidateVersion: str, currentVersion: str) -> bool:
    # isNewerVersion
    if not candidateVersion or candidateVersion == "unknown":
        return False
    if not currentVersion or currentVersion == "unknown":
        return True
    return _versionSortKey(candidateVersion) > _versionSortKey(currentVersion)


def _readJsonUrl(url: str, timeoutSec: float) -> Dict[str, Any]:
    # readJsonUrl
    req = Request(url, headers={"User-Agent": "scipionapi-api/update-check"})
    with urlopen(req, timeout=timeoutSec) as response:
        raw = response.read()
    payload = json.loads(raw.decode("utf-8", errors="replace"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"Manifest is not a JSON object: {url}")
    return payload


def _getUpdateBaseUrl() -> str:
    # getUpdateBaseUrl
    return _normalizeBaseUrl(os.getenv("SCIPIONAPI_UPDATE_BASE_URL"))


def _getUpdateTimeout() -> float:
    # getUpdateTimeout
    try:
        return float((os.getenv("SCIPIONAPI_UPDATE_TIMEOUT") or "300").strip())
    except Exception:
        return 300.0


def _getCurrentApiVersion() -> str:
    # getCurrentApiVersion
    return _normalizeVersionTag(SCIPIONAPI_RELEASE_TAG)


def _getCurrentWebVersion() -> str:
    # getCurrentWebVersion
    return _normalizeVersionTag(
        os.getenv("SCIPIONWEB_LAST_UPDATE_VERSION")
        or os.getenv("SCIPIONAPI_LAST_UPDATE_VERSION")
        or SCIPIONAPI_RELEASE_TAG
    )


def _buildVersionPayload() -> Dict[str, Any]:
    # buildVersionPayload
    apiVersion = _getCurrentApiVersion()
    webVersion = _getCurrentWebVersion()

    return {
        "apiVersion": apiVersion,
        "webVersion": webVersion,
        "currentVersion": apiVersion,
        "lastUpdateVersion": _normalizeVersionTag(os.getenv("SCIPIONAPI_LAST_UPDATE_VERSION")),
        "lastUpdateAt": os.getenv("SCIPIONAPI_LAST_UPDATE_AT") or None,
        "updateBaseUrl": _getUpdateBaseUrl(),
        "serveWeb": (os.getenv("SERVE_WEB") or "").strip() == "1",
        "webDistPath": os.getenv("WEB_DIST_PATH") or None,
    }


def _extractRelease(manifest: Dict[str, Any], version: str) -> Optional[Dict[str, Any]]:
    # extractRelease
    releases = manifest.get("releases")
    if not isinstance(releases, dict):
        return None

    release = releases.get(version)
    if isinstance(release, dict):
        return release

    return None


def _extractFileName(release: Optional[Dict[str, Any]], key: str, fallbackName: str) -> str:
    # extractFileName
    if not isinstance(release, dict):
        return fallbackName

    value = release.get(key)
    if isinstance(value, str):
        return value

    if isinstance(value, dict):
        fileName = value.get("file") or value.get("filename") or value.get("url")
        if fileName:
            return str(fileName)

    return fallbackName


@router.get(
    "/version",
    status_code=status.HTTP_200_OK,
)
def getSystemVersion():
    # getSystemVersion
    return _buildVersionPayload()


@router.get(
    "/update-check",
    status_code=status.HTTP_200_OK,
)
def getUpdateCheck():
    # getUpdateCheck
    versionPayload = _buildVersionPayload()
    baseUrl = versionPayload["updateBaseUrl"]
    manifestUrl = urljoin(baseUrl, DEFAULT_MANIFEST_NAME)
    timeoutSec = _getUpdateTimeout()

    try:
        manifest = _readJsonUrl(manifestUrl, timeoutSec=timeoutSec)
        latestVersion = _normalizeVersionTag(str(manifest.get("latest") or ""))
        currentVersion = versionPayload["currentVersion"]
        updateAvailable = _isNewerVersion(latestVersion, currentVersion)
        release = _extractRelease(manifest, latestVersion)

        apiFile = _extractFileName(
            release,
            "api",
            f"ScipionAPI-{latestVersion}.zip",
        )
        webFile = _extractFileName(
            release,
            "web",
            f"ScipionWeb-{latestVersion}-dist.zip",
        )

        return {
            **versionPayload,
            "checkOk": True,
            "error": None,
            "manifestUrl": manifestUrl,
            "latestVersion": latestVersion,
            "updateAvailable": updateAvailable,
            "apiArchive": apiFile,
            "webArchive": webFile,
            "apiArchiveUrl": urljoin(baseUrl, apiFile),
            "webArchiveUrl": urljoin(baseUrl, webFile),
            "updateCommand": f"./scripts/scipionapi update --version {latestVersion}",
        }

    except (HTTPError, URLError, json.JSONDecodeError, RuntimeError, TimeoutError, OSError) as exc:
        return {
            **versionPayload,
            "checkOk": False,
            "error": str(exc),
            "manifestUrl": manifestUrl,
            "latestVersion": None,
            "updateAvailable": False,
            "apiArchive": None,
            "webArchive": None,
            "apiArchiveUrl": None,
            "webArchiveUrl": None,
            "updateCommand": None,
        }
