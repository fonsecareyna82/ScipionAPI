"""Files uploaded from the user's computer into a project's Uploads folder.

A volume, a mask or a reference made on one's own machine has to reach the
server before a protocol can use it. An upload goes in chunks, so a big file
neither fills the server's memory nor passes a proxy's request limit, and a
dropped connection (a VPN) resumes where it stopped:

1. ``startUpload`` checks the name, the size limit (``SCIPIONWEB_UPLOAD_MAX_GB``)
   and the free disk space, and opens a partial file;
2. ``writeChunk`` appends each chunk at the offset the client says, which must
   be what was received so far (``uploadStatus`` tells it after a drop);
3. ``completeUpload`` gives the file its name, never over an existing file.

Partial files and what they are (``<id>.json``) live in ``Uploads/.partial``;
nothing is kept in memory, so an upload survives a restart of the server.
Partial files untouched for a day are removed when a new upload starts.
"""
from __future__ import annotations

import json
import os
import shutil
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

UPLOADS_FOLDER = "Uploads"
PARTIAL_FOLDER = ".partial"
DEFAULT_MAX_GB = 10.0
# The largest chunk one request may carry; the web sends 8 MB
MAX_CHUNK_BYTES = 64 * 1024 * 1024
# Free space left on the disk after an upload, so a full disk does not stop the database
FREE_SPACE_MARGIN_BYTES = 2 * 1024 ** 3
STALE_PARTIAL_SECONDS = 24 * 3600
MAX_NAME_LENGTH = 255


class UploadError(Exception):
    """A refused upload: status is the HTTP status the route answers."""

    def __init__(self, status: int, message: str, received: Optional[int] = None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.received = received


@dataclass(frozen=True)
class Upload:
    uploadId: str
    name: str
    size: int
    received: int
    userId: int

    def toDict(self) -> dict:
        return {"uploadId": self.uploadId, "name": self.name, "size": self.size, "received": self.received,
                "path": "%s/%s" % (UPLOADS_FOLDER, self.name)}


def maxUploadBytes() -> int:
    """The size limit of one file (SCIPIONWEB_UPLOAD_MAX_GB; 0 or less: no limit)."""
    try:
        gigabytes = float(os.environ.get("SCIPIONWEB_UPLOAD_MAX_GB") or DEFAULT_MAX_GB)
    except ValueError:
        gigabytes = DEFAULT_MAX_GB
    return int(gigabytes * 1024 ** 3) if gigabytes > 0 else 0


def safeName(name: str) -> str:
    """The file name an upload is kept under: a plain, visible name, never a path."""
    text = str(name or "").strip()
    if (not text or text in (".", "..") or text.startswith(".") or len(text) > MAX_NAME_LENGTH
            or any(char in text for char in ("/", "\\", "\0")) or any(ord(char) < 32 for char in text)):
        raise UploadError(400, "Invalid file name: %r" % str(name or ""))
    return text


def uploadsFolder(projectRoot: Path) -> Path:
    return Path(projectRoot) / UPLOADS_FOLDER


def _partialFolder(projectRoot: Path) -> Path:
    return uploadsFolder(projectRoot) / PARTIAL_FOLDER


def _validId(uploadId: str) -> str:
    text = str(uploadId or "")
    if len(text) != 32 or any(char not in "0123456789abcdef" for char in text):
        raise UploadError(404, "Upload not found")
    return text


def _paths(projectRoot: Path, uploadId: str):
    folder = _partialFolder(projectRoot)
    uploadId = _validId(uploadId)
    return folder / (uploadId + ".part"), folder / (uploadId + ".json")


def _load(projectRoot: Path, uploadId: str, userId: int) -> Upload:
    data, meta = _paths(projectRoot, uploadId)
    try:
        info = json.loads(meta.read_text(encoding="utf-8"))
        received = data.stat().st_size
    except (OSError, ValueError):
        raise UploadError(404, "Upload not found")
    # Only who started an upload may go on with it
    if int(info.get("userId", -1)) != int(userId):
        raise UploadError(404, "Upload not found")
    return Upload(uploadId, str(info["name"]), int(info["size"]), received, int(userId))


def _removeStalePartials(folder: Path, now: float) -> None:
    try:
        entries = list(folder.iterdir())
    except OSError:
        return
    for entry in entries:
        try:
            if entry.is_file() and now - entry.stat().st_mtime > STALE_PARTIAL_SECONDS:
                entry.unlink()
        except OSError:
            continue


def startUpload(projectRoot: Path, userId: int, name: str, size: int) -> Upload:
    name = safeName(name)
    if not isinstance(size, int) or size < 0:
        raise UploadError(400, "Invalid file size")
    limit = maxUploadBytes()
    if limit and size > limit:
        raise UploadError(413, "%s is %.1f GB; files up to %.1f GB can be uploaded"
                          % (name, size / 1024 ** 3, limit / 1024 ** 3))
    target = uploadsFolder(projectRoot) / name
    if target.exists() or target.is_symlink():
        raise UploadError(409, "Uploads/%s already exists" % name)
    folder = _partialFolder(projectRoot)
    folder.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(folder).free
    if size + FREE_SPACE_MARGIN_BYTES > free:
        raise UploadError(507, "Not enough free disk space on the server for %s (%.1f GB free)"
                          % (name, free / 1024 ** 3))
    _removeStalePartials(folder, time.time())
    uploadId = uuid.uuid4().hex
    data, meta = _paths(projectRoot, uploadId)
    data.touch()
    meta.write_text(json.dumps({"name": name, "size": size, "userId": int(userId)}), encoding="utf-8")
    return Upload(uploadId, name, size, 0, int(userId))


def uploadStatus(projectRoot: Path, userId: int, uploadId: str) -> Upload:
    return _load(projectRoot, uploadId, userId)


def writeChunk(projectRoot: Path, userId: int, uploadId: str, offset: int, chunk: bytes) -> Upload:
    """Append chunk at offset, which must be what was received so far (409 tells the right one)."""
    upload = _load(projectRoot, uploadId, userId)
    if offset != upload.received:
        raise UploadError(409, "Expected the chunk at byte %d" % upload.received, received=upload.received)
    if len(chunk) > MAX_CHUNK_BYTES:
        raise UploadError(413, "Chunks may be up to %d bytes" % MAX_CHUNK_BYTES)
    if upload.received + len(chunk) > upload.size:
        raise UploadError(400, "More data than the declared size of %d bytes" % upload.size)
    data, _ = _paths(projectRoot, uploadId)
    with open(data, "ab") as handle:
        handle.write(chunk)
    return Upload(upload.uploadId, upload.name, upload.size, upload.received + len(chunk), upload.userId)


def completeUpload(projectRoot: Path, userId: int, uploadId: str) -> Upload:
    upload = _load(projectRoot, uploadId, userId)
    if upload.received != upload.size:
        raise UploadError(409, "Only %d of %d bytes were received" % (upload.received, upload.size),
                          received=upload.received)
    data, meta = _paths(projectRoot, uploadId)
    target = uploadsFolder(projectRoot) / upload.name
    try:
        # A link fails if the name is taken meanwhile: an existing file is never replaced
        os.link(data, target)
    except FileExistsError:
        raise UploadError(409, "Uploads/%s already exists" % upload.name)
    data.unlink()
    meta.unlink(missing_ok=True)
    return upload


def cancelUpload(projectRoot: Path, userId: int, uploadId: str) -> None:
    _load(projectRoot, uploadId, userId)
    for path in _paths(projectRoot, uploadId):
        path.unlink(missing_ok=True)
