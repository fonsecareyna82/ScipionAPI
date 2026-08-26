import json
from pathlib import Path
import zipfile

import pytest

import scipionapi_cli.release as releaseModule
from scipionapi_cli.release import (
    _normalizeLogin,
    _normalizeRemoteDir,
    _resolveAssetPath,
)


def test_NormalizeRemoteDirRemovesTrailingSlash():
    assert _normalizeRemoteDir(
        "/home/scipion/scipionfiles/downloads/scipion/scipionWeb/"
    ) == "/home/scipion/scipionfiles/downloads/scipion/scipionWeb"


@pytest.mark.parametrize(
    "value",
    ["", "/", ".", "..", "bad path", "bad;path"],
)
def test_NormalizeRemoteDirRejectsUnsafeValues(value):
    with pytest.raises(RuntimeError):
        _normalizeRemoteDir(value)


def test_NormalizeLoginAcceptsScipionSshLogin():
    assert _normalizeLogin(
        "scipion@nolan.cnb.csic.es"
    ) == "scipion@nolan.cnb.csic.es"


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


def test_ResolveWebRootUsesSiblingRepository(tmp_path):
    apiRoot = tmp_path / "ScipionAPI"
    webRoot = tmp_path / "ScipionWeb"

    apiRoot.mkdir()
    webRoot.mkdir()

    (webRoot / "package.json").write_text(
        json.dumps({
            "name": "scipionweb",
            "version": "4.0.0",
        }),
        encoding="utf-8",
    )

    assert releaseModule._resolveWebRoot(
        apiRoot
    ) == webRoot.resolve()


def test_ResolvePairedReleaseVersionMatchesApiAndWeb(
    monkeypatch,
    tmp_path,
):
    webRoot = tmp_path / "ScipionWeb"
    webRoot.mkdir()

    (webRoot / "package.json").write_text(
        json.dumps({
            "name": "scipionweb",
            "version": "4.0.0",
        }),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        releaseModule,
        "SCIPIONAPI_VERSION",
        "4.0.0",
    )

    assert releaseModule._resolvePairedReleaseVersion(
        webRoot
    ) == "v4.0.0"


def test_ResolvePairedReleaseVersionRejectsMismatch(
    monkeypatch,
    tmp_path,
):
    webRoot = tmp_path / "ScipionWeb"
    webRoot.mkdir()

    (webRoot / "package.json").write_text(
        json.dumps({
            "name": "scipionweb",
            "version": "4.0.1",
        }),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        releaseModule,
        "SCIPIONAPI_VERSION",
        "4.0.0",
    )

    with pytest.raises(
        RuntimeError,
        match="Release version mismatch",
    ):
        releaseModule._resolvePairedReleaseVersion(
            webRoot
        )


def test_RequestedReleaseVersionIsOnlyAnAssertion(
    monkeypatch,
    tmp_path,
):
    webRoot = tmp_path / "ScipionWeb"
    webRoot.mkdir()

    (webRoot / "package.json").write_text(
        json.dumps({
            "name": "scipionweb",
            "version": "4.0.0",
        }),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        releaseModule,
        "SCIPIONAPI_VERSION",
        "4.0.0",
    )

    with pytest.raises(
        RuntimeError,
        match="Requested release version does not match",
    ):
        releaseModule._resolvePairedReleaseVersion(
            webRoot,
            requestedVersion="v4.0.1",
        )


def test_BuildApiReleaseArchiveUsesManagedPaths(
    monkeypatch,
    tmp_path,
):
    repoRoot = tmp_path / "ScipionAPI"
    repoRoot.mkdir()

    appPath = repoRoot / "app"
    appPath.mkdir()

    (appPath / "main.py").write_text(
        "print('api')",
        encoding="utf-8",
    )

    cachePath = appPath / "__pycache__"
    cachePath.mkdir()

    (cachePath / "main.pyc").write_bytes(
        b"cache"
    )

    (repoRoot / "pyproject.toml").write_text(
        "[project]\nname='scipionapi'\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        releaseModule,
        "API_MANAGED_PATHS",
        [
            "app",
            "pyproject.toml",
        ],
    )

    archivePath = (
        tmp_path
        / "ScipionAPI-v4.0.0.zip"
    )

    releaseModule._buildApiReleaseArchive(
        repoRoot,
        archivePath,
    )

    with zipfile.ZipFile(
        archivePath,
        "r",
    ) as archive:
        names = set(
            archive.namelist()
        )

    assert "app/main.py" in names
    assert "pyproject.toml" in names
    assert not any(
        "__pycache__" in name
        for name in names
    )


def test_BuildWebReleaseArchiveKeepsAppRoot(
    tmp_path,
):
    webDistPath = (
        tmp_path
        / "dist"
        / "app"
    )

    assetsPath = (
        webDistPath
        / "assets"
    )

    assetsPath.mkdir(
        parents=True
    )

    (webDistPath / "index.html").write_text(
        "<html></html>",
        encoding="utf-8",
    )

    (assetsPath / "main.js").write_text(
        "console.log('web')",
        encoding="utf-8",
    )

    archivePath = (
        tmp_path
        / "ScipionWeb-v4.0.0-dist.zip"
    )

    releaseModule._buildWebReleaseArchive(
        webDistPath,
        archivePath,
    )

    with zipfile.ZipFile(
        archivePath,
        "r",
    ) as archive:
        names = set(
            archive.namelist()
        )

    assert "app/index.html" in names
    assert "app/assets/main.js" in names
    assert "index.html" not in names


def test_ReleaseBuildRunsWebBuild(
    monkeypatch,
    tmp_path,
):
    apiRoot = tmp_path / "ScipionAPI"
    webRoot = tmp_path / "ScipionWeb"
    downloads = tmp_path / "downloads"

    apiRoot.mkdir()
    webRoot.mkdir()

    (webRoot / "package.json").write_text(
        json.dumps({
            "name": "scipionweb",
            "version": "4.0.0",
        }),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        releaseModule,
        "resolveRepoRoot",
        lambda: apiRoot,
    )

    monkeypatch.setattr(
        releaseModule,
        "SCIPIONAPI_VERSION",
        "4.0.0",
    )

    monkeypatch.setattr(
        releaseModule,
        "_requireTool",
        lambda name: name,
    )

    calls = []

    def fakeRun(
        args,
        captureOutput=False,
        check=True,
        cwd=None,
    ):
        calls.append(
            (args, cwd)
        )

        webDist = (
            webRoot
            / "dist"
            / "app"
        )

        webDist.mkdir(
            parents=True
        )

        (webDist / "index.html").write_text(
            "<html></html>",
            encoding="utf-8",
        )

    monkeypatch.setattr(
        releaseModule,
        "_run",
        fakeRun,
    )

    monkeypatch.setattr(
        releaseModule,
        "_buildApiReleaseArchive",
        lambda repoRoot, archivePath:
            archivePath.write_bytes(b"api"),
    )

    releaseModule.releaseBuildCommand(
        webRoot=str(webRoot),
        downloadsDir=str(downloads),
    )

    assert calls == [
        (
            ["npm", "run", "build:web"],
            webRoot.resolve(),
        )
    ]

    assert (
        downloads
        / "ScipionAPI-v4.0.0.zip"
    ).is_file()

    assert (
        downloads
        / "ScipionWeb-v4.0.0-dist.zip"
    ).is_file()


def test_ReleaseCommandBuildsBeforeUpload(
    monkeypatch,
    tmp_path,
):
    apiPath = tmp_path / "ScipionAPI-v4.0.0.zip"
    webPath = tmp_path / "ScipionWeb-v4.0.0-dist.zip"

    buildCalls = []
    uploadCalls = []

    def fakeBuildCommand(**kwargs):
        buildCalls.append(kwargs)
        return "v4.0.0", apiPath, webPath

    def fakeUploadCommand(**kwargs):
        uploadCalls.append(kwargs)

    monkeypatch.setattr(
        releaseModule,
        "releaseBuildCommand",
        fakeBuildCommand,
    )

    monkeypatch.setattr(
        releaseModule,
        "releaseUploadCommand",
        fakeUploadCommand,
    )

    releaseModule.releaseCommand(
        upload=True,
        downloadsDir=str(tmp_path),
        dryRun=True,
        yes=True,
    )

    assert len(buildCalls) == 1
    assert len(uploadCalls) == 1

    assert uploadCalls[0]["version"] == "v4.0.0"
    assert uploadCalls[0]["apiFile"] == str(apiPath)
    assert uploadCalls[0]["webFile"] == str(webPath)


def test_ReleaseCommandBuildOnlyDoesNotUpload(
    monkeypatch,
    tmp_path,
):
    apiPath = tmp_path / "ScipionAPI-v4.0.0.zip"
    webPath = tmp_path / "ScipionWeb-v4.0.0-dist.zip"

    monkeypatch.setattr(
        releaseModule,
        "releaseBuildCommand",
        lambda **kwargs: (
            "v4.0.0",
            apiPath,
            webPath,
        ),
    )

    uploads = []

    monkeypatch.setattr(
        releaseModule,
        "releaseUploadCommand",
        lambda **kwargs: uploads.append(kwargs),
    )

    releaseModule.releaseCommand(
        upload=False,
        downloadsDir=str(tmp_path),
    )

    assert uploads == []


def test_ReleaseCommandCanUploadExistingArchives(
    monkeypatch,
    tmp_path,
):
    buildCalls = []
    uploadCalls = []

    monkeypatch.setattr(
        releaseModule,
        "releaseBuildCommand",
        lambda **kwargs: buildCalls.append(kwargs),
    )

    monkeypatch.setattr(
        releaseModule,
        "releaseUploadCommand",
        lambda **kwargs: uploadCalls.append(kwargs),
    )

    releaseModule.releaseCommand(
        upload=True,
        buildArtifacts=False,
        version="v4.0.0",
        downloadsDir=str(tmp_path),
        apiFile="ScipionAPI-v4.0.0.zip",
        webFile="ScipionWeb-v4.0.0-dist.zip",
        dryRun=True,
        yes=True,
    )

    assert buildCalls == []
    assert len(uploadCalls) == 1
    assert uploadCalls[0]["version"] == "v4.0.0"
    assert uploadCalls[0]["apiFile"] == "ScipionAPI-v4.0.0.zip"
    assert uploadCalls[0]["webFile"] == "ScipionWeb-v4.0.0-dist.zip"


def test_ReleaseDryRunDoesNotUpload(monkeypatch, tmp_path):
    repo_root = Path(__file__).resolve().parents[3]
    web_root = tmp_path / "ScipionWeb"
    downloads = tmp_path / "downloads"

    web_root.mkdir()
    downloads.mkdir()

    (web_root / "package.json").write_text(
        json.dumps({
            "name": "scipionweb",
            "version": "4.0.0",
        }),
        encoding="utf-8",
    )

    (downloads / "ScipionAPI-v4.0.0.zip").write_bytes(b"api")
    (downloads / "ScipionWeb-v4.0.0-dist.zip").write_bytes(b"web")

    monkeypatch.setattr(
        releaseModule,
        "resolveRepoRoot",
        lambda: repo_root,
    )
    monkeypatch.setattr(
        releaseModule,
        "SCIPIONAPI_VERSION",
        "4.0.0",
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
        webRoot=str(web_root),
        downloadsDir=str(downloads),
        dryRun=True,
        yes=True,
    )

    assert uploads == []


def test_ReleaseDefaultsMatchScipionDownloadServer():
    assert releaseModule.DEFAULT_RELEASE_LOGIN == (
        "scipion@nolan.cnb.csic.es"
    )
    assert releaseModule.DEFAULT_RELEASE_REMOTE_DIR == (
        "/home/scipion/scipionfiles/downloads/scipion/scipionWeb"
    )