"""The plugin catalog is quick and never empty: the live one when Scipion's server answers (and it is saved), the
saved one when not, and the plugins ScipionWeb knows when there is nothing saved. Versions come from PyPI."""
import json

import pytest

from app.backend.api.services import plugin_catalog
from app.backend.api.services.plugin_catalog import PluginCatalog

CATALOG = {"scipion-em-alpha": {"pipName": "scipion-em-alpha", "name": "alpha", "logo": "alpha.png"},
           "scipion-em-beta": {"pipName": "scipion-em-beta", "name": "beta"}}


def pypiAnswer(version="3.1.0", files=True):
    return {"info": {"summary": "Does things", "author": "Someone", "home_page": "https://x", "license": "GPL"},
            "releases": {version: [{"comment_text": "scipion-3.0", "upload_time": "2025-01-01T00:00:00",
                                    "url": "https://files"}] if files else [],
                         "0.1": []}}


class FakePluginInfo:
    """Only what plugin_catalog uses of Scipion's PluginInfo."""

    def __init__(self, pipName="", name="", remote=True, **kwargs):
        self.pipName, self.name, self.logo = pipName, name, kwargs.get("logo", "")
        self.compatibleReleases, self.latestRelease, self.summary = {}, "999.9.9", ""

    def getPipData(self, info, keys):
        return next((info[key] for key in keys if info.get(key)), " ")

    def getCompatiblePipReleases(self, pipJsonData):
        releases = dict(pipJsonData["releases"])
        releases["latest"] = max(releases) if releases else "0.0.0"
        return releases

    def setLocalPluginInfo(self):
        pass


@pytest.fixture(autouse=True)
def fakeScipion(monkeypatch):
    import scipion.install.plugin_funcs as funcs

    monkeypatch.setattr(funcs, "PluginInfo", FakePluginInfo)
    monkeypatch.setattr(plugin_catalog, "_status", {"source": None, "savedAt": None, "loadedAt": 0.0})


def serving(catalog=None, pypi=None):
    asked = []

    def fetch(url):
        asked.append(url)
        if "pypi.org" in url:
            name = url.split("/pypi/")[1].split("/")[0]
            if pypi is None or name not in pypi:
                raise OSError("PyPI does not answer")
            return pypi[name]
        if catalog is None:
            raise OSError("Connection timed out")
        return catalog

    return fetch, asked


def test_live_catalog_with_its_pypi_data_is_saved(tmp_path):
    fetch, _ = serving(CATALOG, {"scipion-em-alpha": pypiAnswer(), "scipion-em-beta": pypiAnswer("1.0")})
    path = tmp_path / "cache" / "plugin_catalog.json"
    plugins = PluginCatalog(fetch, path=path, shipped=tmp_path / "none.json").getPlugins()
    assert plugins["scipion-em-alpha"].latestRelease == "3.1.0"
    assert plugins["scipion-em-alpha"].summary == "Does things"
    assert plugin_catalog.status()["source"] == "live"
    saved = json.loads(path.read_text())
    assert set(saved["catalog"]) == set(CATALOG)
    # Only what PluginInfo reads is kept, and releases without files are left out
    assert saved["pypi"]["scipion-em-alpha"]["releases"] == {
        "3.1.0": [{"comment_text": "scipion-3.0", "upload_time": "2025-01-01T00:00:00"}]}
    assert "license" not in saved["pypi"]["scipion-em-alpha"]["info"]


def test_server_down_shows_the_saved_catalog_with_fresh_pypi_data(tmp_path):
    path = tmp_path / "plugin_catalog.json"
    path.write_text(json.dumps({"savedAt": "2026-11-01T10:00:00+00:00", "catalog": CATALOG,
                                "pypi": {"scipion-em-beta": plugin_catalog.trimPypi(pypiAnswer("0.9"))}}))
    fetch, _ = serving(None, {"scipion-em-alpha": pypiAnswer("3.2.0")})
    plugins = PluginCatalog(fetch, path=path, shipped=tmp_path / "none.json").getPlugins()
    assert plugins["scipion-em-alpha"].latestRelease == "3.2.0"
    # PyPI did not answer for beta: its saved data is used
    assert plugins["scipion-em-beta"].latestRelease == "0.9"
    assert plugin_catalog.status() == {"source": "saved", "savedAt": "2026-11-01T10:00:00+00:00"}


def test_without_a_saved_catalog_the_shipped_one_then_the_known_plugins(tmp_path):
    shipped = tmp_path / "shipped.json"
    shipped.write_text(json.dumps({"savedAt": "2026-10-01T00:00:00+00:00", "catalog": CATALOG, "pypi": {}}))
    fetch, _ = serving(None, {"scipion-em-alpha": pypiAnswer()})
    assert set(PluginCatalog(fetch, path=tmp_path / "missing.json", shipped=shipped).getPlugins()) == set(CATALOG)
    assert plugin_catalog.status()["source"] == "shipped"

    local = {"scipion-em-gamma": {"pipName": "scipion-em-gamma", "name": "gamma"}}
    plugins = PluginCatalog(serving(None, {"scipion-em-gamma": pypiAnswer()})[0], path=tmp_path / "missing.json",
                            shipped=tmp_path / "none.json", local=lambda: local).getPlugins()
    assert list(plugins) == ["scipion-em-gamma"]
    assert plugin_catalog.status()["source"] == "local"


def test_without_pypi_only_one_request_is_tried_and_versions_are_unknown(tmp_path):
    fetch, asked = serving(CATALOG, None)
    plugins = PluginCatalog(fetch, path=tmp_path / "c.json", shipped=tmp_path / "none.json").getPlugins()
    assert set(plugins) == set(CATALOG)
    assert plugins["scipion-em-alpha"].latestRelease == ""
    assert len([url for url in asked if "pypi.org" in url]) == 2  # the first plugin, then pip itself


def test_a_plugin_without_a_release_for_this_scipion_is_left_out(tmp_path):
    fetch, _ = serving(CATALOG, {"scipion-em-alpha": dict(pypiAnswer(files=False), releases={}),
                                 "scipion-em-beta": pypiAnswer()})
    plugins = PluginCatalog(fetch, path=tmp_path / "c.json", shipped=tmp_path / "none.json").getPlugins()
    assert list(plugins) == ["scipion-em-beta"]


def test_a_catalog_that_is_not_live_is_asked_again_after_a_while(monkeypatch):
    plugin_catalog._setStatus("saved", None)
    assert not plugin_catalog.shouldRetry()
    assert plugin_catalog.shouldRetry(now=plugin_catalog._status["loadedAt"] + plugin_catalog.RETRY_SECONDS)
    plugin_catalog._setStatus("live", None)
    assert not plugin_catalog.shouldRetry(now=plugin_catalog._status["loadedAt"] + 10 ** 6)
