"""Short-lived signed links to download one file of the file browser.

The API authenticates with a bearer token, which a plain link cannot carry.
So the browser first asks, authenticated, for a link to one file (checked
against the browsing boundary, see fs_browser), and then downloads it as a
normal link: the browser's own download manager streams it to disk, shows its
progress and resumes it (HTTP range requests) if the connection drops, as
over a VPN.

The link names the absolute file it was issued for, the user and project,
and when it expires; it is signed with the server's secret, so it cannot be
pointed at another file or reused after it expires.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass
from typing import Optional

TOKEN_PREFIX = "fd."
# Long enough to resume a big download after a dropped connection.
DOWNLOAD_LINK_SECONDS = 2 * 60 * 60
_SIGNATURE_LENGTH = 43
_MAX_TOKEN = 8192


@dataclass(frozen=True)
class DownloadGrant:
    path: str
    userId: int
    projectId: int
    expiresAt: int


def _secret() -> bytes:
    from app.backend.utils.jwt import SECRET_KEY
    return ("fs-download:" + str(SECRET_KEY)).encode("utf-8")


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(payload: str) -> str:
    return _b64(hmac.new(_secret(), payload.encode("ascii"), hashlib.sha256).digest())[:_SIGNATURE_LENGTH]


def signDownload(path: str, userId: int, projectId: int, seconds: int = DOWNLOAD_LINK_SECONDS,
                 now: Optional[float] = None) -> DownloadGrant:
    """A grant to download this absolute file until it expires."""
    if not os.path.isabs(path) or "\x00" in path:
        raise ValueError("invalid_download_path")
    expiresAt = int((time.time() if now is None else now) + seconds)
    return DownloadGrant(path=path, userId=int(userId), projectId=int(projectId), expiresAt=expiresAt)


def encodeGrant(grant: DownloadGrant) -> str:
    payload = _b64(json.dumps([grant.path, grant.userId, grant.projectId, grant.expiresAt],
                              separators=(",", ":")).encode("utf-8"))
    return "%s%s.%s" % (TOKEN_PREFIX, payload, _sign(payload))


def readDownloadToken(token, projectId: int, now: Optional[float] = None) -> Optional[DownloadGrant]:
    """The grant of a valid, unexpired token for this project; None otherwise."""
    if type(token) is not str or not token.startswith(TOKEN_PREFIX) or len(token) > _MAX_TOKEN:
        return None
    payload, _, signature = token[len(TOKEN_PREFIX):].partition(".")
    if not payload or not signature or not hmac.compare_digest(signature, _sign(payload)):
        return None
    try:
        path, userId, tokenProjectId, expiresAt = json.loads(_unb64(payload).decode("utf-8"))
    except (ValueError, TypeError, UnicodeError):
        return None
    if type(tokenProjectId) is not int or tokenProjectId != int(projectId):
        return None
    if type(expiresAt) is not int or expiresAt < (time.time() if now is None else now):
        return None
    if type(path) is not str or not os.path.isabs(path):
        return None
    return DownloadGrant(path=path, userId=int(userId), projectId=tokenProjectId, expiresAt=expiresAt)
