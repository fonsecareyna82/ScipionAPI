"""A binary served by Scipion's download server is not installed when the server does not answer: it says so at
once. Binaries installed with conda/pip/git only need void.tgz, which is made here."""
import tarfile

import pytest

from app.backend.api.services import binary_downloads
from app.backend.api.services.binary_downloads import DownloadServerDown, checkDownloads, pendingServerDownloads

SERVER = "https://scipion.cnb.csic.es/downloads/scipion/software"


class Command:
    def __init__(self, cmd, targets):
        self._cmd, self._targets = cmd, targets


class Target:
    def __init__(self, name, commands, deps=(), default=True):
        self.name, self.commands, self.deps, self.default = name, commands, list(deps), default

    def getName(self):
        return self.name

    def getCommands(self):
        return self.commands

    def getDeps(self):
        return self.deps

    def isDefault(self):
        return self.default


class Environment:
    def __init__(self, *targets):
        self.targets = {target.name: target for target in targets}

    def getTarget(self, name):
        return self.targets[name]

    def getTargetList(self):
        return list(self.targets.values())


def download(folder, tar, server=SERVER):
    path = str(folder / tar)
    return Command("wget -nv -c -O %s.part %s/em/%s\nmv -v %s.part %s" % (path, server, tar, path, path), [path])


@pytest.fixture(autouse=True)
def forget(monkeypatch):
    monkeypatch.setattr(binary_downloads, "_answered", {"at": 0.0, "value": None})


def environment(folder):
    (folder / "done-1.0.tgz").write_bytes(b"x")
    return Environment(
        Target("library-2.0", [download(folder, "library-2.0.tgz")], default=False),
        Target("ctffind-5.0", [download(folder, "ctffind-5.0.tgz")], deps=["library-2.0"]),
        Target("done-1.0", [download(folder, "done-1.0.tgz")]),
        Target("cistem-1.0", [download(folder, "cistem.tgz", "https://grigoriefflab.example.org")]),
        Target("topaz-0.2", [download(folder, "void.tgz"), Command("conda create -n topaz", [])]))


def test_finds_what_still_has_to_come_from_scipions_server(tmp_path):
    env = environment(tmp_path)
    assert pendingServerDownloads(env, ["ctffind-5.0"], SERVER) == ["ctffind-5.0", "library-2.0"]
    # Downloaded before, served by another site, or only void.tgz: nothing needed from the server
    assert pendingServerDownloads(env, ["done-1.0", "cistem-1.0", "topaz-0.2"], SERVER) == []
    # void.tgz was missing: it is made where the download would have left it
    assert (tmp_path / "void.tgz").is_file()


def test_server_down_stops_at_once_and_names_the_binaries(tmp_path, monkeypatch):
    monkeypatch.setattr(binary_downloads, "downloadServer", lambda: SERVER)
    env = environment(tmp_path)

    def down(url):
        raise OSError("Connection timed out")

    with pytest.raises(DownloadServerDown, match="ctffind-5.0, library-2.0"):
        checkDownloads(env, ["ctffind-5.0"], ask=down)
    checkDownloads(env, ["topaz-0.2"], ask=down)  # conda: no server needed
    monkeypatch.setattr(binary_downloads, "_answered", {"at": 0.0, "value": None})
    checkDownloads(env, ["ctffind-5.0"], ask=lambda url: None)


def test_the_server_check_is_remembered_for_a_minute():
    asked = []
    assert binary_downloads.serverAnswers(SERVER, ask=asked.append)
    assert binary_downloads.serverAnswers(SERVER, ask=asked.append)
    assert asked == [SERVER]


def test_void_tgz_is_made_when_missing(tmp_path):
    binary_downloads.makeVoidTgz(str(tmp_path / "em"))
    with tarfile.open(tmp_path / "em" / "void.tgz") as archive:
        assert archive.getnames() == ["void", "void/void.txt"]
