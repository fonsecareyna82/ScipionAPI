"""A failed plugin installation goes back to the environment it found: pip, the EM binaries and conda."""
import json
import subprocess

import pytest

from app.backend.api.services import plugin_install_journal as journalModule
from app.backend.api.services.plugin_install_journal import InstallJournal, describeRollback, rollBackUnfinished


@pytest.fixture(autouse=True)
def neverTheRealEnvironment(monkeypatch):
    """Nothing here may list or change the real pip packages or conda environments."""
    def refuse(*args, **kwargs):
        raise AssertionError("a test reached the real environment: %s" % (args,))

    monkeypatch.setattr(journalModule, "_run", refuse)
    monkeypatch.setattr(journalModule, "pipPackages", refuse)
    monkeypatch.setattr(journalModule, "condaEnvironments", refuse)


class FakeEnvironment:
    """pip and conda as the commands see them; the EM folder is a real temporary folder."""

    def __init__(self, tmp_path, monkeypatch):
        self.packages = {"numpy": "1.24.4", "scipion-em": "3.9.0", "pip": "24.0"}
        self.environments = ["/conda/base", "/conda/envs/scipion4Web"]
        self.offline = set()
        self.commands = []
        self.em = tmp_path / "em"
        self.em.mkdir()
        monkeypatch.setattr(journalModule, "emFolder", lambda: self.em)
        monkeypatch.setattr(journalModule, "condaExecutable", lambda: "conda")
        monkeypatch.setattr(journalModule, "condaEnvironments", lambda conda: list(self.environments))
        monkeypatch.setattr(journalModule, "pipPackages", self.pipPackages)

    def pipPackages(self, python=None):
        return dict(self.packages)

    def run(self, command, timeout=None):
        self.commands.append(command)
        if command[1:4] == ["-m", "pip", "uninstall"]:
            for name in command[5:]:
                self.packages.pop(name, None)
        elif command[1:4] == ["-m", "pip", "install"]:
            name, version = command[-1].split("==")
            if name in self.offline:
                return subprocess.CompletedProcess(command, 1, "", "ERROR: No matching distribution found")
            self.packages[name] = version
        elif command[:3] == ["conda", "env", "remove"]:
            self.environments.remove(command[-1])
        return subprocess.CompletedProcess(command, 0, "", "")


@pytest.fixture
def environment(tmp_path, monkeypatch):
    return FakeEnvironment(tmp_path, monkeypatch)


def test_AFailedInstallationLeavesTheEnvironmentAsItFoundIt(environment, tmp_path):
    # Binaries that were there before: a folder, and a link to a program installed by hand
    (environment.em / "ctffind-4.1.14").mkdir()
    handInstalled = tmp_path / "opt" / "motioncor3"
    handInstalled.mkdir(parents=True)
    (handInstalled / "MotionCor3").write_text("binary")
    (environment.em / "motioncor3-1.1.1").symlink_to(handInstalled)

    journal = InstallJournal.begin("task-1", "scipion-em-warp", folder=tmp_path / "journals")
    assert journal.path.is_file()

    # The installation adds the plugin and a dependency, upgrades numpy, starts a binary and a conda env
    environment.packages.update({"scipion-em-warp": "3.2.0", "mrcfile": "1.5.0", "numpy": "1.26.1"})
    (environment.em / "warp-2.0.0" / "bin").mkdir(parents=True)
    newLink = environment.em / "warp-latest"
    newLink.symlink_to(handInstalled)
    environment.environments.append("/conda/envs/warp-2.0.0")

    report = journal.rollBack(run=environment.run, packages=environment.pipPackages)

    assert environment.packages == {"numpy": "1.24.4", "scipion-em": "3.9.0", "pip": "24.0"}
    assert report["removedPackages"] == ["mrcfile", "scipion-em-warp"]
    assert report["restoredPackages"] == ["numpy==1.24.4"]
    assert sorted(path.name for path in environment.em.iterdir()) == ["ctffind-4.1.14", "motioncor3-1.1.1"]
    # A link is removed as a link: what it points to stays
    assert (handInstalled / "MotionCor3").read_text() == "binary"
    assert environment.environments == ["/conda/base", "/conda/envs/scipion4Web"]
    assert describeRollback(report) == (
        "Rolled back: removed mrcfile, scipion-em-warp; put back numpy==1.24.4; removed the binaries warp-2.0.0, "
        "warp-latest; removed the conda environments warp-2.0.0")

    journal.finish()
    assert not journal.path.exists()


def test_AFailedUpdateGoesBackToThePreviousReleaseAndNamesWhatItCouldNotPutBack(environment, tmp_path):
    environment.packages["scipion-em-relion"] = "3.1.0"
    journal = InstallJournal.begin("task-2", "scipion-em-relion", folder=tmp_path / "journals")

    environment.packages.update({"scipion-em-relion": "3.2.0", "numpy": "1.26.1"})
    environment.offline.add("numpy")

    report = journal.rollBack(run=environment.run, packages=environment.pipPackages)

    assert environment.packages["scipion-em-relion"] == "3.1.0"
    assert report["notRestored"] == [{"package": "numpy", "version": "1.24.4",
                                      "error": "ERROR: No matching distribution found"}]
    assert describeRollback(report).endswith(
        "ROLLBACK INCOMPLETE: numpy could not be put back to 1.24.4 (ERROR: No matching distribution found)")
    # The installer's own tools are never touched
    assert not any("pip==" in part for command in environment.commands for part in command)


def test_AnInstallationAWorkerLeftHalfDoneIsRolledBackWhenItStartsAgain(environment, tmp_path, monkeypatch):
    folder = tmp_path / "journals"
    journal = InstallJournal.begin("task-3", "scipion-em-cryolo", folder=folder)
    environment.packages["scipion-em-cryolo"] = "3.0.0"
    alive = InstallJournal.begin("task-4", "scipion-em-imod", folder=folder)
    data = json.loads(alive.path.read_text())
    data["pid"] = 999999
    alive.path.write_text(json.dumps(data))
    data = json.loads(journal.path.read_text())
    data["pid"] = 999998
    journal.path.write_text(json.dumps(data))

    monkeypatch.setattr(journalModule, "_run", environment.run)
    done = rollBackUnfinished(folder=folder, log=lambda message: None, isAlive=lambda pid: pid == 999999)

    assert [item["subject"] for item in done] == ["scipion-em-cryolo"]
    assert done[0]["taskId"] == "task-3" and "removed scipion-em-cryolo" in done[0]["summary"]
    assert "scipion-em-cryolo" not in environment.packages
    # The installation still running keeps its journal
    assert not journal.path.exists() and alive.path.exists()


def test_PipNamesAreComparedAsPipDoes():
    assert journalModule.canonicalName("Scipion_EM-Xmipp") == "scipion-em-xmipp"
    assert journalModule.canonicalName("ruamel.yaml") == "ruamel-yaml"
