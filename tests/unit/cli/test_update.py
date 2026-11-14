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
# ******************************************************************************

import os
import tempfile
from collections import namedtuple
from pathlib import Path

import pytest

import scipionapi_cli.update as updateModule


def test_InstallUpdatedApiRefreshesScipionCoreFromPyproject(
    monkeypatch,
    tmp_path,
):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        "\n".join([
            "[project]",
            "name = \"scipionapi\"",
            "dependencies = [",
            "  \"scipion-pyworkflow @ git+https://example.org/scipion-pyworkflow.git@devel\",",
            "  \"scipion-em @ git+https://example.org/scipion-em.git@devel\",",
            "  \"scipion-app @ git+https://example.org/scipion-app.git@devel\",",
            "  \"fastapi==0.116.1\",",
            "]",
            "",
        ]),
        encoding="utf-8",
    )

    pipCalls = []

    monkeypatch.setattr(
        updateModule,
        "_runPipInstall",
        lambda repoRoot, args: pipCalls.append(
            (repoRoot, list(args))
        ),
    )
    monkeypatch.setattr(
        updateModule,
        "_printStep",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        updateModule,
        "_printInfo",
        lambda *args, **kwargs: None,
    )

    updateModule._installUpdatedApi(tmp_path)

    assert pipCalls == [
        (
            tmp_path,
            [
                "--upgrade",
                "--force-reinstall",
                "--no-deps",
                "scipion-pyworkflow @ git+https://example.org/scipion-pyworkflow.git@devel",
                "scipion-em @ git+https://example.org/scipion-em.git@devel",
                "scipion-app @ git+https://example.org/scipion-app.git@devel",
            ],
        ),
        (
            tmp_path,
            ["-e", str(tmp_path)],
        ),
    ]


GB = 1024 ** 3
_Usage = namedtuple("Usage", "total used free")


def _quiet(monkeypatch):
    for name in ("_printStep", "_printInfo", "_printWarning", "_printSuccess", "_printPanel", "_printKeyValueTable"):
        monkeypatch.setattr(updateModule, name, lambda *args, **kwargs: None)


def test_AnUpdateStopsBeforeChangingAnythingWhenADiskIsShort(monkeypatch, tmp_path):
    """pip filled / mid-update on a server; a full disk also stops PostgreSQL."""
    _quiet(monkeypatch)
    monkeypatch.setattr(updateModule.shutil, "disk_usage", lambda path: _Usage(100 * GB, 98 * GB, 2 * GB))

    with pytest.raises(RuntimeError) as error:
        updateModule._checkFreeSpace({"scipion_home": tmp_path}, updateModule._minFreeBytes({}))

    assert "Not enough free disk space" in str(error.value)
    assert "SCIPIONAPI_UPDATE_MIN_FREE_GB" in str(error.value)


def test_EnoughSpaceOrNoMinimumLetsTheUpdateGoOn(monkeypatch, tmp_path):
    _quiet(monkeypatch)
    monkeypatch.setattr(updateModule.shutil, "disk_usage", lambda path: _Usage(100 * GB, 90 * GB, 10 * GB))
    updateModule._checkFreeSpace({"scipion_home": tmp_path}, updateModule._minFreeBytes({}))

    monkeypatch.setattr(updateModule.shutil, "disk_usage", lambda path: _Usage(100 * GB, 99 * GB, 1 * GB))
    updateModule._checkFreeSpace({"scipion_home": tmp_path}, updateModule._minFreeBytes({"SCIPIONAPI_UPDATE_MIN_FREE_GB": "0"}))
    assert updateModule._minFreeBytes({"SCIPIONAPI_UPDATE_MIN_FREE_GB": "0.5"}) == GB // 2
    assert updateModule._minFreeBytes({"SCIPIONAPI_UPDATE_MIN_FREE_GB": "lots"}) == 5 * GB


def test_ADiskIsCheckedOnceWhateverPathsItHolds(monkeypatch, tmp_path):
    _quiet(monkeypatch)
    checked = []
    monkeypatch.setattr(updateModule.shutil, "disk_usage",
                        lambda path: checked.append(path) or _Usage(100 * GB, 0, 50 * GB))

    updateModule._checkFreeSpace({"scipion_home": tmp_path, "env": tmp_path / "not" / "there"}, 5 * GB)

    assert checked == [tmp_path]


def test_TemporaryFilesOfTheUpdateGoUnderScipionHome(monkeypatch, tmp_path):
    monkeypatch.setenv("TMPDIR", "/tmp")
    monkeypatch.setattr(tempfile, "tempdir", None)

    updateModule._useUpdateTemp(tmp_path / "work" / "tmp")

    assert os.environ["TMPDIR"] == str(tmp_path / "work" / "tmp")
    assert Path(tempfile.mkdtemp()).parent == tmp_path / "work" / "tmp"


def test_WorkDirectoriesOfEarlierUpdatesAreRemoved(monkeypatch, tmp_path):
    monkeypatch.setattr(updateModule, "_updatesDir", lambda scipionHome: scipionHome / "updates")
    work = tmp_path / "updates" / "work"
    for name in ("20261029T100000Z", "20261030T170017Z", "current"):
        (work / name / "downloads").mkdir(parents=True)
        (work / name / "downloads" / "big.zip").write_bytes(b"x" * 10)

    updateModule._cleanupWorkDirs(tmp_path, keep=work / "current")

    assert [path.name for path in work.iterdir()] == ["current"]


# Where an update comes from: GitHub first, then the CNB server ------------------------------------------------

import json as _json

GITHUB_API = "https://api.github.com/repos/fonsecareyna82/ScipionWeb/releases?per_page=1"
GITHUB_BASE = "https://github.com/fonsecareyna82/ScipionWeb/releases/download/v4.0.0/"
CNB_BASE = "https://scipion.cnb.csic.es/downloads/scipion/scipionWeb/"
RELEASE_MANIFEST = {"latest": "v4.0.0", "releases": {"v4.0.0": {
    "api": {"file": "ScipionAPI-v4.0.0.zip", "sha256": "aaa"}, "web": {"file": "ScipionWeb-v4.0.0-dist.zip"}}}}


def _serve(monkeypatch, served):
    asked = []

    def read(url, timeoutSec):
        asked.append(url)
        if url not in served:
            raise updateModule.URLError("not served")
        return _json.dumps(served[url])

    monkeypatch.setattr(updateModule, "_readUrlText", read)
    return asked


def test_AnUpdateTakesTheNewestGithubReleaseTestReleasesIncluded(monkeypatch):
    asked = _serve(monkeypatch, {GITHUB_API: [{"tag_name": "v4.0.0", "prerelease": True}],
                                 GITHUB_BASE + "manifest.json": RELEASE_MANIFEST})
    base, release, fallback = updateModule._resolveSource(None, {}, "latest", 60)
    assert base == GITHUB_BASE
    assert release == ("v4.0.0", "ScipionAPI-v4.0.0.zip", "ScipionWeb-v4.0.0-dist.zip", "aaa", None)
    assert fallback == CNB_BASE
    assert not any(CNB_BASE in url for url in asked)


def test_AnUpdateUsesTheCnbServerWhenGithubHasNoRelease(monkeypatch):
    _serve(monkeypatch, {GITHUB_API: [], CNB_BASE + "manifest.json": RELEASE_MANIFEST})
    base, release, fallback = updateModule._resolveSource(None, {}, "latest", 60)
    assert (base, release[0], fallback) == (CNB_BASE, "v4.0.0", None)


def test_AnUpdateOfAVersionNotOnGithubUsesTheCnbServer(monkeypatch):
    _serve(monkeypatch, {GITHUB_BASE + "manifest.json": {"latest": "v3.9.0", "releases": {"v3.9.0": {}}},
                         CNB_BASE + "manifest.json": RELEASE_MANIFEST})
    base, release, _ = updateModule._resolveSource(None, {}, "4.0.0", 60)
    assert (base, release[3]) == (CNB_BASE, "aaa")


def test_AnUpdateFromAnAddressGivenAsksOnlyThere(monkeypatch):
    mirror = "https://mirror.example.org/scipionweb/"
    asked = _serve(monkeypatch, {mirror + "manifest.json": RELEASE_MANIFEST})
    base, release, fallback = updateModule._resolveSource(mirror.rstrip("/"), {}, "latest", 60)
    assert (base, release[0], fallback) == (mirror, "v4.0.0", None)
    assert asked == [mirror + "manifest.json"]
