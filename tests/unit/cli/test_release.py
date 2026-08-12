from pathlib import Path

import pytest

import scipionapi_cli.release as releaseModule
from scipionapi_cli.release import (
    _normalizeLogin,
    _normalizeRemoteDir,
    _resolveAssetPath,
)


def test_NormalizeRemoteDirRemovesTrailingSlash():
    assert _normalizeRemoteDir(
        "scipionfiles/downloads/scipion/scipionWeb/"
    ) == "scipionfiles/downloads/scipion/scipionWeb"


@pytest.mark.parametrize(
    "value",
    ["", "/", ".", "..", "bad path", "bad;path"],
)
def test_NormalizeRemoteDirRejectsUnsafeValues(value):
    with pytest.raises(RuntimeError):
        _normalizeRemoteDir(value)


def test_NormalizeLoginAcceptsScipionSshLogin():
    assert _normalizeLogin(
        "scipion@scipion.cnb.csic.es"
    ) == "scipion@scipion.cnb.csic.es"


@pytest.mark.parametrize("value", ["", "-bad", "bad login", "bad;login"])
def test_NormalizeLoginRejectsUnsafeValues(value):
    with pytest.raises(RuntimeError):
        _normalizeLogin(value)


def test_ResolveAssetPathUsesDownloadsDirectory(tmp_path):
    downloads = tmp_path / "downloads"
    downloads.mkdir()

    path = _resolveAssetPath(
        downloads,
        None,
        "ScipionAPI-v4.0.0.zip",
    )

    assert path == (downloads / "ScipionAPI-v4.0.0.zip").resolve()


def test_ResolveAssetPathPreservesAbsolutePath(tmp_path):
    archive = tmp_path / "custom-api.zip"

    path = _resolveAssetPath(
        tmp_path / "other",
        str(archive),
        "ignored.zip",
    )

    assert path == archive.resolve()


def test_ReleaseDryRunDoesNotUpload(monkeypatch, tmp_path):
    repo_root = Path(__file__).resolve().parents[3]
    downloads = tmp_path / "downloads"
    downloads.mkdir()

    (downloads / "ScipionAPI-v4.0.0.zip").write_bytes(b"api")
    (downloads / "ScipionWeb-v4.0.0-dist.zip").write_bytes(b"web")

    monkeypatch.setattr(
        releaseModule,
        "resolveRepoRoot",
        lambda: repo_root,
    )
    monkeypatch.setattr(
        releaseModule,
        "_requireTool",
        lambda name: name,
    )
    monkeypatch.setattr(
        releaseModule,
        "_remoteIsDirectory",
        lambda *args, **kwargs: True,
    )
    monkeypatch.setattr(
        releaseModule,
        "_downloadRemoteManifest",
        lambda *args, **kwargs: False,
    )
    monkeypatch.setattr(
        releaseModule,
        "_remoteReleaseAlreadyExists",
        lambda *args, **kwargs: [],
    )

    uploads = []
    monkeypatch.setattr(
        releaseModule,
        "_atomicUpload",
        lambda *args, **kwargs: uploads.append((args, kwargs)),
    )

    releaseModule.releaseUploadCommand(
        version="v4.0.0",
        downloadsDir=str(downloads),
        dryRun=True,
        yes=True,
    )

    assert uploads == []
