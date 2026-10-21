"""Resetting a protocol removes its folder under <project>/Runs, and nothing else."""
from types import SimpleNamespace

from app.backend.runtime.protocol_reset_service import RuntimeProtocolResetService
from app.backend.utils import background_delete


class Protocol:
    def __init__(self, path, tmp=None):
        self.path, self.tmp, self.cleaned = path, tmp, 0

    def _getPath(self):
        return self.path

    def _getTmpPath(self):
        return self.tmp

    def getObjId(self):
        return 2

    def cleanWorkingDir(self):
        self.cleaned += 1


def test_a_relative_folder_is_resolved_against_the_project_not_the_current_folder(tmp_path, monkeypatch):
    project = tmp_path / "project"
    folder = project / "Runs" / "000002_ProtA"
    (folder / "extra").mkdir(parents=True)
    elsewhere = tmp_path / "server-cwd"
    (elsewhere / "Runs" / "000002_ProtA").mkdir(parents=True)
    monkeypatch.chdir(elsewhere)

    protocol = Protocol("Runs/000002_ProtA", tmp="Runs/000002_ProtA/tmp")
    RuntimeProtocolResetService._cleanWorkingDirInBackground(protocol, str(project))
    background_delete.waitForBackgroundDeletes(timeout=10)

    assert not folder.exists()
    assert (elsewhere / "Runs" / "000002_ProtA").is_dir()
    assert protocol.cleaned == 0


def test_without_a_folder_under_runs_scipion_cleans_it_and_nothing_is_removed(tmp_path, monkeypatch):
    (tmp_path / "keep.txt").write_text("x")
    monkeypatch.chdir(tmp_path)
    for path, projectPath in (("", str(tmp_path)), ("Runs", str(tmp_path)), ("../other", str(tmp_path)),
                              ("Runs/000002_ProtA", None)):
        protocol = Protocol(path)
        RuntimeProtocolResetService._cleanWorkingDirInBackground(protocol, projectPath)
        assert protocol.cleaned == 1, path
    background_delete.waitForBackgroundDeletes(timeout=10)
    assert (tmp_path / "keep.txt").exists()


def test_the_project_folder_comes_from_the_current_project():
    assert RuntimeProtocolResetService._currentProjectPath(SimpleNamespace(path="/data/p")) == "/data/p"
    assert RuntimeProtocolResetService._currentProjectPath(SimpleNamespace(getPath=lambda: "/data/q")) == "/data/q"
    assert RuntimeProtocolResetService._currentProjectPath(None) is None
