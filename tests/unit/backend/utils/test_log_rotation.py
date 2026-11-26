import os

from app.backend.utils import log_rotation
from app.backend.utils.log_rotation import rotateIfBig


def test_SmallLogIsLeftAlone(tmp_path):
    log = tmp_path / "celery.log"
    log.write_bytes(b"x" * 10)

    assert rotateIfBig(log, limit=100, keep=3) is False
    assert log.read_bytes() == b"x" * 10
    assert not (tmp_path / "celery.log.1").exists()


def test_BigLogIsCopiedAndEmptiedInPlace(tmp_path):
    log = tmp_path / "celery.log"
    log.write_bytes(b"a" * 200)
    inode = log.stat().st_ino

    assert rotateIfBig(log, limit=100, keep=3) is True
    assert (tmp_path / "celery.log.1").read_bytes() == b"a" * 200
    assert log.read_bytes() == b""
    # Same file: the service's open handle goes on writing into it
    assert log.stat().st_ino == inode


def test_WriterThatAppendsKeepsWritingAfterTheRotation(tmp_path):
    log = tmp_path / "app.log"
    with open(log, "a") as writer:
        writer.write("old" * 100)
        writer.flush()
        rotateIfBig(log, limit=100, keep=3)
        writer.write("new")
        writer.flush()

    assert log.read_text() == "new"


def test_OlderCopiesMoveUpAndOnlyTheLastOnesAreKept(tmp_path):
    log = tmp_path / "celery.log"
    for text in ("first", "second", "third", "fourth"):
        log.write_text(text * 50)
        rotateIfBig(log, limit=10, keep=2)

    assert (tmp_path / "celery.log.1").read_text() == "fourth" * 50
    assert (tmp_path / "celery.log.2").read_text() == "third" * 50
    assert not (tmp_path / "celery.log.3").exists()


def test_MissingLogIsNotAnError(tmp_path):
    assert rotateIfBig(tmp_path / "none.log", limit=1, keep=1) is False


def test_LimitsComeFromTheEnvironment(monkeypatch):
    monkeypatch.setenv("LOG_MAX_MB", "7")
    monkeypatch.setenv("LOG_BACKUPS", "5")
    assert log_rotation.maxBytes() == 7 * 1024 * 1024
    assert log_rotation.backups() == 5

    monkeypatch.setenv("LOG_MAX_MB", "nonsense")
    assert log_rotation.maxBytes() == log_rotation.DEFAULT_MAX_MB * 1024 * 1024


def test_NoThreadWithoutALogFile(monkeypatch):
    monkeypatch.delenv(log_rotation.LOG_FILE_ENV, raising=False)
    monkeypatch.setattr(log_rotation, "_thread", None)
    log_rotation.startLogRotation()
    assert log_rotation._thread is None
