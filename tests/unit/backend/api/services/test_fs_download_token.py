"""Signed links to download one file of the file browser."""
from app.backend.api.services import fs_download_token as tokens


def test_a_link_reads_back_for_its_project_until_it_expires():
    grant = tokens.signDownload("/data/movies/m1.tif", userId=3, projectId=7, seconds=60, now=1000)
    token = tokens.encodeGrant(grant)
    assert tokens.readDownloadToken(token, 7, now=1030) == grant
    assert tokens.readDownloadToken(token, 7, now=1061) is None
    assert tokens.readDownloadToken(token, 8, now=1030) is None


def test_a_changed_link_is_refused():
    token = tokens.encodeGrant(tokens.signDownload("/data/a.mrc", 3, 7, now=1000))
    other = tokens.encodeGrant(tokens.signDownload("/etc/passwd", 3, 7, now=1000))
    payload, signature = token[len(tokens.TOKEN_PREFIX):].split(".")
    otherPayload = other[len(tokens.TOKEN_PREFIX):].split(".")[0]
    # Another file's payload under this signature.
    assert tokens.readDownloadToken(tokens.TOKEN_PREFIX + otherPayload + "." + signature, 7, now=1001) is None
    for broken in ("", "fd.", "fd.abc", "vf." + payload + "." + signature, token + "x", None, 12):
        assert tokens.readDownloadToken(broken, 7, now=1001) is None


def test_only_absolute_paths_are_signed():
    import pytest
    with pytest.raises(ValueError):
        tokens.signDownload("relative/a.mrc", 1, 1)
