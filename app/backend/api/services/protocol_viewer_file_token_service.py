"""Signed references to project files produced by ProtocolViewer actions.

A viewer action may show a file that is not a stored protocol output (e.g. an
Xmipp ``.xmd`` block or a ``.sqlite`` written in ``extra/``). The web reads it
through the existing output metadata routes, using an opaque token in place
of the output name. The token is signed by the server, so clients cannot
point it at arbitrary paths, and it is bound to one project.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from typing import List, Optional, Sequence, Tuple, Union

VIEWER_FILE_TOKEN_PREFIX = "vf."
_SIGNATURE_LENGTH = 32
_MAX_PATH = 1024
_MAX_PATHS = 64


def _secret() -> bytes:
    from app.backend.utils.jwt import SECRET_KEY
    return ("protocol-viewer-file:" + str(SECRET_KEY)).encode("utf-8")


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def isSafeProjectRelativePath(path) -> bool:
    if type(path) is not str or not 0 < len(path) <= _MAX_PATH:
        return False
    if "\x00" in path or "\\" in path or os.path.isabs(path):
        return False
    parts = path.split("/")
    return all(part not in ("", ".", "..") for part in parts)


def isViewerFileToken(value) -> bool:
    return type(value) is str and value.startswith(VIEWER_FILE_TOKEN_PREFIX)


def _validPaths(value) -> bool:
    if isinstance(value, str):
        return isSafeProjectRelativePath(value)
    return (isinstance(value, list) and 0 < len(value) <= _MAX_PATHS
            and all(isSafeProjectRelativePath(path) for path in value))


def signViewerFileToken(projectId: int, relativePath: Union[str, Sequence[str]]) -> str:
    """Sign one file, or a list of files shown together (e.g. several volumes)."""
    if not isinstance(relativePath, str):
        relativePath = list(relativePath)
    if type(projectId) is not int or not _validPaths(relativePath):
        raise ValueError("invalid_viewer_file")
    payload = _b64(json.dumps([projectId, relativePath],
                              separators=(",", ":")).encode("utf-8"))
    signature = hmac.new(_secret(), payload.encode("ascii"),
                         hashlib.sha256).digest()
    return "%s%s.%s" % (VIEWER_FILE_TOKEN_PREFIX, payload,
                        _b64(signature)[:_SIGNATURE_LENGTH])


def readViewerFileToken(token, projectId: int) -> Optional[str]:
    """Return the project-relative path of a single-file token, or None."""
    value = _readTokenPayload(token, projectId)
    return value if isinstance(value, str) else None


def readViewerFileTokenPaths(token, projectId: int) -> Optional[List[str]]:
    """Return the project-relative paths of any valid token, or None."""
    value = _readTokenPayload(token, projectId)
    if value is None:
        return None
    return [value] if isinstance(value, str) else list(value)


def _readTokenPayload(token, projectId: int):
    if not isViewerFileToken(token) or len(token) > 16384:
        return None
    body = token[len(VIEWER_FILE_TOKEN_PREFIX):]
    payload, _, signature = body.partition(".")
    if not payload or not signature:
        return None
    expected = _b64(hmac.new(_secret(), payload.encode("ascii"),
                             hashlib.sha256).digest())[:_SIGNATURE_LENGTH]
    if not hmac.compare_digest(signature, expected):
        return None
    try:
        value = json.loads(_unb64(payload).decode("utf-8"))
    except (ValueError, UnicodeError):
        return None
    if (not isinstance(value, list) or len(value) != 2 or value[0] != projectId
            or type(value[0]) is not int or not _validPaths(value[1])):
        return None
    return value[1]


def _resolveInside(root: str, relative: str) -> str:
    absolute = os.path.realpath(os.path.join(root, relative))
    if os.path.commonpath([absolute, root]) != root or not os.path.isfile(absolute):
        raise LookupError("viewer_file_not_found")
    return absolute


def resolveViewerFileToken(token, projectId: int, projectPath: str) -> Tuple[str, str]:
    """Absolute path of a single-file token, which must still be inside the project."""
    relative = readViewerFileToken(token, projectId)
    if relative is None or not projectPath:
        raise LookupError("invalid_viewer_file")
    return _resolveInside(os.path.realpath(projectPath), relative), relative


def resolveViewerFileTokenPaths(token, projectId: int, projectPath: str) -> List[Tuple[str, str]]:
    """(absolute, relative) paths of any token; every file must be inside the project."""
    relatives = readViewerFileTokenPaths(token, projectId)
    if relatives is None or not projectPath:
        raise LookupError("invalid_viewer_file")
    root = os.path.realpath(projectPath)
    return [(_resolveInside(root, relative), relative) for relative in relatives]
