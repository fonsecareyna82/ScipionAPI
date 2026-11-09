"""Which pip package installs a plugin known by its module."""
import pytest

from app.backend.api.services import plugin_packages as packages

CATALOG = {"scipion-em-xmipp": {"name": "Xmipp", "pipName": "scipion-em-xmipp"},
           "scipion-em-prody": {"name": "Prody", "pipName": "scipion-em-prody"},
           "scipion-chem": {"name": "chem", "pipName": "scipion-chem"},
           "scipion-chem-autodock": {"name": "autodock", "pipName": "scipion-chem-autodock"},
           "scipion-em-relion": {"name": "Relion", "pipName": "scipion-em-relion"},
           "scipion-em-grigoriefflab": {"name": "Cistem", "pipName": "scipion-em-grigoriefflab"}}


@pytest.fixture(autouse=True)
def nothingInstalled(monkeypatch):
    packages.resetCaches()
    monkeypatch.setattr(packages, "installedModulePackages", lambda refresh=False: {"tomo": "scipion-em-tomo"})
    yield
    packages.resetCaches()


@pytest.mark.parametrize("module, package", [
    ("relion", "scipion-em-relion"),        # the rule
    ("xmipp3", "scipion-em-xmipp"),         # a known exception
    ("autodock", "scipion-chem-autodock"),  # a chemistry plugin
    ("pwchem", "scipion-chem"),
    ("prody2", "scipion-em-prody"),
    ("cistem", "scipion-em-grigoriefflab"),  # only the catalog's shown name says it
    ("tomo", "scipion-em-tomo"),             # installed here
    ("nonexistent", None),                   # nothing says it: not guessed
])
def test_APluginsPackageIsFoundInTheCatalog(module, package):
    assert packages.packageForModule(module, fetch=lambda: CATALOG) == package


def test_WhatAWorkflowSaysComesFirst():
    assert packages.packageForModule("relion", {"relion": "scipion-em-relion-dev"}, fetch=lambda: CATALOG) == \
        "scipion-em-relion-dev"


def test_WithoutTheCatalogTheUsualNameIsAnsweredUnchecked():
    def offline():
        raise ConnectionError("no network")

    assert packages.packageForModule("xmipp3", fetch=offline) == "scipion-em-xmipp"
    assert packages.packageForModule("relion", fetch=offline) == "scipion-em-relion"


def test_TheCatalogIsReadOnceAnHour():
    calls = []

    def fetch():
        calls.append(1)
        return CATALOG

    packages.packageForModule("relion", fetch=fetch)
    packages.packageForModule("xmipp3", fetch=fetch)
    assert len(calls) == 1
