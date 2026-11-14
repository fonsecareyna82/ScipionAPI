"""The dashboard's update check looks for the newest release on GitHub first and on the CNB server next, quickly;
an address an administrator chose is the only source, and the CNB default stored by old updates does not count."""
import json

import pytest

import scipionapi_cli.update as updateModule
from app.backend.api.routers import system_router

GITHUB_API = "https://api.github.com/repos/fonsecareyna82/ScipionWeb/releases?per_page=1"
GITHUB_BASE = "https://github.com/fonsecareyna82/ScipionWeb/releases/download/v4.1.0/"
CNB_BASE = "https://scipion.cnb.csic.es/downloads/scipion/scipionWeb/"
MANIFEST = {"latest": "v4.1.0", "releases": {"v4.1.0": {"api": {"file": "ScipionAPI-v4.1.0.zip"},
                                                        "web": {"file": "ScipionWeb-v4.1.0-dist.zip"}}}}


@pytest.fixture
def served(monkeypatch):
    answers, asked = {}, []

    def read(url, timeoutSec):
        asked.append((url, timeoutSec))
        if url not in answers:
            raise OSError("Connection timed out")
        return answers[url]

    monkeypatch.setattr(updateModule, "_readUrlText", lambda url, timeoutSec: json.dumps(read(url, timeoutSec)))
    monkeypatch.setattr(system_router, "_readJsonUrl", read)
    monkeypatch.delenv("SCIPIONAPI_UPDATE_BASE_URL", raising=False)
    monkeypatch.delenv("SCIPIONWEB_GITHUB_REPO", raising=False)
    monkeypatch.setattr(system_router, "SCIPIONAPI_RELEASE_TAG", "v4.0.0")
    return answers, asked


def test_newest_release_comes_from_github(served):
    answers, asked = served
    answers.update({GITHUB_API: [{"tag_name": "v4.1.0", "prerelease": True}], GITHUB_BASE + "manifest.json": MANIFEST})
    check = system_router.getUpdateCheck()
    assert check["checkOk"] and check["updateAvailable"]
    assert (check["latestVersion"], check["updateBaseUrl"]) == ("v4.1.0", GITHUB_BASE)
    assert check["webArchiveUrl"] == GITHUB_BASE + "ScipionWeb-v4.1.0-dist.zip"
    assert all(timeout <= system_router.CHECK_TIMEOUT_SECONDS for _, timeout in asked)


def test_the_cnb_server_when_github_does_not_answer(served):
    answers, _ = served
    answers[CNB_BASE + "manifest.json"] = MANIFEST
    check = system_router.getUpdateCheck()
    assert (check["checkOk"], check["updateBaseUrl"]) == (True, CNB_BASE)


def test_neither_answers(served):
    check = system_router.getUpdateCheck()
    assert check["checkOk"] is False
    assert "GitHub:" in check["error"] and "CNB download server:" in check["error"]


def test_an_address_chosen_is_the_only_source_but_the_old_cnb_default_is_not_one(served, monkeypatch):
    answers, asked = served
    mirror = "https://mirror.example.org/scipionweb/"
    answers[mirror + "manifest.json"] = MANIFEST
    monkeypatch.setenv("SCIPIONAPI_UPDATE_BASE_URL", mirror)
    assert system_router.getUpdateCheck()["updateBaseUrl"] == mirror
    assert [url for url, _ in asked] == [mirror + "manifest.json"]

    monkeypatch.setenv("SCIPIONAPI_UPDATE_BASE_URL", CNB_BASE)
    answers.update({GITHUB_API: [{"tag_name": "v4.1.0"}], GITHUB_BASE + "manifest.json": MANIFEST})
    assert system_router.getUpdateCheck()["updateBaseUrl"] == GITHUB_BASE
    assert updateModule.chosenBaseUrl(CNB_BASE, None) is None
