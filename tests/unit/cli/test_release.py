import json
from pathlib import Path
import zipfile

import pytest

githubCalls = []

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

    monkeypatch.setattr(releaseModule, "releaseGithubCommand", lambda **kwargs: githubCalls.append(kwargs))
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

    monkeypatch.setattr(releaseModule, "releaseGithubCommand", lambda **kwargs: githubCalls.append(kwargs))
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

    monkeypatch.setattr(releaseModule, "releaseGithubCommand", lambda **kwargs: githubCalls.append(kwargs))
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


# Publishing on GitHub too ----------------------------------------------------------------------------------

from scipionapi_cli import github_release


def test_ReleaseIsPublishedOnGithubEvenWhenTheCnbServerFails(monkeypatch, tmp_path):
    published = []

    def cnbFails(**kwargs):
        raise RuntimeError("ssh: connect to host nolan.cnb.csic.es: Connection timed out")

    monkeypatch.setattr(releaseModule, "releaseUploadCommand", cnbFails)
    monkeypatch.setattr(releaseModule, "releaseGithubCommand", lambda **kwargs: published.append(kwargs))
    with pytest.raises(RuntimeError, match="not published everywhere. CNB download server: ssh"):
        releaseModule.releaseCommand(upload=True, buildArtifacts=False, version="v4.0.0",
                                     downloadsDir=str(tmp_path), yes=True, force=True)
    assert published[0]["version"] == "v4.0.0"
    assert published[0]["prerelease"] is True
    assert published[0]["force"] is True


def test_OnlyOnePlaceCanBeChosen(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(releaseModule, "releaseUploadCommand", lambda **kwargs: calls.append("cnb"))
    monkeypatch.setattr(releaseModule, "releaseGithubCommand", lambda **kwargs: calls.append("github"))
    releaseModule.releaseCommand(upload=True, buildArtifacts=False, version="v4.0.0", downloadsDir=str(tmp_path),
                                 toCnb=False)
    assert calls == ["github"]


class FakeGithub:
    def __init__(self, existing=None):
        self.calls, self.existing = [], existing

    def __call__(self, method, url, token, body=None, data=None, contentType="application/json"):
        self.calls.append((method, url.split("github.com")[1], body, contentType))
        if method == "GET":
            return (200, self.existing) if self.existing else (404, None)
        if method == "POST" and url.endswith("/releases"):
            return 201, {"id": 77}
        if method == "PATCH":
            return 200, {"html_url": "https://github.com/o/r/releases/tag/v4.0.0"}
        return 204, None


def assets(tmp_path):
    files = []
    for name in ("ScipionAPI-v4.0.0.zip", "manifest.json", "install.sh"):
        (tmp_path / name).write_bytes(b"x")
        files.append(tmp_path / name)
    return files


def test_GithubReleaseIsADraftWithItsFilesBeforeItIsPublished(tmp_path):
    github = FakeGithub()
    url = github_release.publishRelease("o/r", "v4.0.0", assets(tmp_path), "token", "abc123", call=github,
                                        log=lambda message: None)
    assert url.endswith("/releases/tag/v4.0.0")
    methods = [(method, path.split("?")[0]) for method, path, _, _ in github.calls]
    assert methods == [("GET", "/repos/o/r/releases/tags/v4.0.0"), ("POST", "/repos/o/r/releases"),
                       ("POST", "/repos/o/r/releases/77/assets"), ("POST", "/repos/o/r/releases/77/assets"),
                       ("POST", "/repos/o/r/releases/77/assets"), ("PATCH", "/repos/o/r/releases/77")]
    draft = github.calls[1][2]
    assert (draft["tag_name"], draft["draft"], draft["prerelease"], draft["target_commitish"]) == (
        "v4.0.0", True, True, "abc123")
    assert [contentType for _, _, _, contentType in github.calls[2:5]] == [
        "application/zip", "application/json", "text/x-shellscript"]
    assert github.calls[-1][2] == {"draft": False, "tag_name": "v4.0.0", "target_commitish": "abc123",
                                   "prerelease": True}


def test_ReplacingAGithubReleaseRemovesTheEarlierOneOnlyAtTheEnd(tmp_path):
    github = FakeGithub(existing={"id": 5})
    with pytest.raises(RuntimeError, match="already exists"):
        github_release.publishRelease("o/r", "v4.0.0", assets(tmp_path), "t", "abc", call=github, log=print)

    github = FakeGithub(existing={"id": 5})
    github_release.publishRelease("o/r", "v4.0.0", assets(tmp_path), "t", "abc", replace=True, call=github,
                                  log=lambda message: None)
    methods = [(method, path) for method, path, _, _ in github.calls]
    assert github.calls[1][2]["tag_name"] == "v4.0.0-replacement"
    assert methods[-3:] == [("DELETE", "/repos/o/r/releases/5"), ("DELETE", "/repos/o/r/git/refs/tags/v4.0.0"),
                            ("PATCH", "/repos/o/r/releases/77")]
    assert github.calls[-1][2]["tag_name"] == "v4.0.0"
