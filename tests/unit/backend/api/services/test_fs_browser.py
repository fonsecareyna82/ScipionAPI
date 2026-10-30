"""Where the remote file browser may look and write."""
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.backend.api.services import fs_browser


class Mapper:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def getProjectProtocolByProtocolId(self, projectId, protocolId):
        self.calls.append((projectId, protocolId))
        return self.rows.get(str(protocolId))


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "MyProject"
    (root / "Runs" / "000012_ProtImportMovies" / "extra").mkdir(parents=True)
    return root


def test_project_scope_starts_in_the_protocol_folder_without_loading_the_project(project):
    mapper = Mapper({"12": {"protocolId": "12", "protocolClassName": "ProtImportMovies"}})
    browser = fs_browser.resolveBrowserRoot(mapper, 7, "12", str(project))
    assert browser.root == project.resolve()
    assert browser.start == browser.protocolRoot == "Runs/000012_ProtImportMovies"
    assert mapper.calls == [(7, "12")]
    assert browser.toDict()["projectRootAbs"] == project.resolve().as_posix()


def test_filesystem_scope_reads_everything_from_the_protocol_folder(project):
    mapper = Mapper({"12": {"protocolId": "12", "protocolClassName": "ProtImportMovies"}})
    browser = fs_browser.resolveBrowserRoot(mapper, 7, "12", str(project), scope="filesystem")
    assert browser.root.as_posix() == "/"
    assert browser.start == (project / "Runs" / "000012_ProtImportMovies").as_posix().lstrip("/")
    # Nothing is written outside a project, even with the filesystem readable.
    with pytest.raises(HTTPException) as error:
        fs_browser.writableTarget(browser, str(project / "x.json"))
    assert error.value.status_code == 403


def test_new_or_never_run_protocols_start_in_the_project(project):
    mapper = Mapper({"30": {"protocolId": "30", "protocolClassName": "ProtNotRunYet"}})
    assert fs_browser.resolveBrowserRoot(mapper, 7, "30", str(project)).start == ""
    unsaved = fs_browser.resolveBrowserRoot(Mapper({}), 7, "fake-protocol-id-for-browser-paths-resolution",
                                            str(project), scope="filesystem")
    assert unsaved.start == project.resolve().as_posix().lstrip("/")
    with pytest.raises(HTTPException) as error:
        fs_browser.resolveBrowserRoot(Mapper({}), 7, "99", str(project))
    assert error.value.status_code == 404


def test_imports_never_go_above_the_ceiling(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / "user" / "data").mkdir(parents=True)
    monkeypatch.setenv("SCIPION_IMPORT_BROWSER_CEILING", str(home))
    monkeypatch.setenv("SCIPION_IMPORT_BROWSER_ROOT", str(home / "user"))
    assert fs_browser.importRoot() == (home / "user").resolve()
    monkeypatch.setenv("SCIPION_IMPORT_BROWSER_ROOT", str(tmp_path))
    assert fs_browser.importRoot() == home.resolve()
    browser = fs_browser.resolveBrowserRoot(None, -1, "-1", None)
    assert browser.kind == "import" and browser.root == home.resolve()


def test_writes_stay_in_the_project_or_are_json_files_in_the_import_area(tmp_path, monkeypatch, project):
    mapper = Mapper({})
    inProject = fs_browser.resolveBrowserRoot(mapper, 7, "", str(project))
    assert fs_browser.writableTarget(inProject, "Runs/notes.txt") == (project / "Runs" / "notes.txt").resolve()
    with pytest.raises(HTTPException):
        fs_browser.writableTarget(inProject, "../escape.txt")

    home = tmp_path / "home"
    (home / "user").mkdir(parents=True)
    (home / "user" / ".bashrc").write_text("keep")
    monkeypatch.setenv("SCIPION_IMPORT_BROWSER_CEILING", str(home))
    monkeypatch.setenv("SCIPION_IMPORT_BROWSER_ROOT", str(home))
    importArea = fs_browser.resolveBrowserRoot(None, -1, "-1", None)
    assert fs_browser.writableTarget(importArea, "user/workflow.json") == (home / "user" / "workflow.json").resolve()
    for refused in ("user/.bashrc", "user/run.sh", ".config/w.json", "user/.hidden/w.json"):
        with pytest.raises(HTTPException) as error:
            fs_browser.writableTarget(importArea, refused)
        assert error.value.status_code == 403


def _limitedBrowser(tmp_path, monkeypatch, canBrowseServer=False):
    project = tmp_path / "projects" / "demo"
    (project / "Runs").mkdir(parents=True)
    data = tmp_path / "data" / "lab"
    (data / "movies").mkdir(parents=True)
    (tmp_path / "data" / "other-lab").mkdir()
    monkeypatch.setenv("SCIPIONWEB_DATA_ROOTS", str(data))
    browser = fs_browser.resolveBrowserRoot(Mapper({}), 1, None, str(project), "filesystem",
                                            canBrowseServer=canBrowseServer)
    return browser, project, data


def test_WithoutTheBrowseServerPermissionOnlyTheProjectAndTheDataFoldersAreReached(tmp_path, monkeypatch):
    browser, project, data = _limitedBrowser(tmp_path, monkeypatch)

    assert browser.toDict()["allowedRoots"] == [project.as_posix(), data.as_posix()]
    assert fs_browser.isAllowed(browser, project / "Runs")
    assert fs_browser.isAllowed(browser, data / "movies" / "a.tif")
    assert not fs_browser.isAllowed(browser, tmp_path / "data" / "other-lab")
    with pytest.raises(HTTPException) as error:
        fs_browser.checkAllowed(browser, Path("/etc/passwd"))
    assert error.value.status_code == 403
    # Folders on the way to a data folder can be listed, showing only that way
    fs_browser.checkAllowed(browser, tmp_path / "data", folder=True)
    listing = [{"name": "lab", "isDir": True}, {"name": "other-lab", "isDir": True}, {"name": "x.txt", "isDir": False}]
    assert fs_browser.filterListing(browser, tmp_path / "data", listing) == [{"name": "lab", "isDir": True}]
    assert fs_browser.filterListing(browser, data, listing) == listing


def test_TheBrowseServerPermissionOrNoDataFoldersLeaveTheFilesystemOpen(tmp_path, monkeypatch):
    browser, _, _ = _limitedBrowser(tmp_path, monkeypatch, canBrowseServer=True)
    assert browser.allowed is None and fs_browser.isAllowed(browser, Path("/etc"))

    monkeypatch.delenv("SCIPIONWEB_DATA_ROOTS")
    project = tmp_path / "projects" / "demo"
    open_ = fs_browser.resolveBrowserRoot(Mapper({}), 1, None, str(project), "filesystem", canBrowseServer=False)
    assert open_.allowed is None and open_.toDict()["allowedRoots"] is None
