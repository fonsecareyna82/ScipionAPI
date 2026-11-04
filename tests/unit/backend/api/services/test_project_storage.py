"""What a project folder takes on the disk, and the names of the users' projects folders."""
import os

from app.backend.api.services import project_storage as storage
from app.backend.utils.background_delete import TRASH_FOLDER


def _write(path, size):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    return path


def _disk(path):
    return storage._diskBytes(os.stat(path, follow_symlinks=False))


def test_AProjectIsMeasuredByItsRunsItsUploadsAndTheRest(tmp_path):
    project = tmp_path / "projects" / "scipion" / "Apoferritin"
    runs = _write(project / "Runs" / "000002_ProtImportMovies" / "extra" / "movie.mrc", 300000)
    upload = _write(project / "Uploads" / "gain.mrc", 50000)
    database = _write(project / "project.sqlite", 8000)
    # Imported movies are links to the microscope's data: not the project's
    microscope = _write(tmp_path / "offload" / "movie_1.tif", 900000)
    (project / "Runs" / "000002_ProtImportMovies" / "extra" / "movie_1.tif").symlink_to(microscope)
    (project / "Runs" / "data").symlink_to(tmp_path / "offload", target_is_directory=True)
    # A file with two hard links is counted once
    os.link(runs, project / "Runs" / "000002_ProtImportMovies" / "extra" / "same_movie.mrc")
    # What is being removed is not counted
    _write(project / TRASH_FOLDER / "000010_ProtCTFFind.abc", 700000)

    measured = storage.measureFolder(project, pauseEvery=0)

    assert measured == {"totalBytes": _disk(runs) + _disk(upload) + _disk(database), "runsBytes": _disk(runs),
                        "uploadsBytes": _disk(upload), "files": 3}


def test_ALargeProjectIsWalkedWithPauses(tmp_path):
    for number in range(7):
        _write(tmp_path / "Runs" / ("file_%d" % number), 10)
    pauses = []

    storage.measureFolder(tmp_path, pauseEvery=3, pauseSeconds=0.5, sleep=pauses.append)

    # 8 entries (the Runs folder and its 7 files)
    assert pauses == [0.5, 0.5]


def test_ALinkedProjectIsMeasuredWhereItIsAndAMissingOneSaysSo(tmp_path):
    root = tmp_path / "projects"
    elsewhere = tmp_path / "disk2" / "OldProject"
    data = _write(elsewhere / "Runs" / "000002_ProtImportMovies" / "logs" / "run.log", 4000)
    root.mkdir()
    (root / "OldProject").symlink_to(elsewhere, target_is_directory=True)

    linked = storage.measureProject(str(root / "OldProject"), root, sleep=lambda seconds: None)
    assert linked["location"] == "linked" and linked["measuredPath"] == str(elsewhere.resolve())
    assert linked["totalBytes"] == linked["runsBytes"] == _disk(data) and linked["error"] is None

    assert storage.measureProject(str(elsewhere), root)["location"] == "external"
    (root / "scipion" / "New").mkdir(parents=True)
    assert storage.measureProject(str(root / "scipion" / "New"), root)["location"] == "managed"

    missing = storage.measureProject(str(root / "scipion" / "Gone"), root)
    assert missing["error"] == "The project folder is not there" and missing["totalBytes"] is None


def test_AUsersFolderIsNamedAfterTheirEmail():
    assert storage.folderNameOf("scipion@cnb.csic.es", 3) == "scipion"
    assert storage.folderNameOf("Ana.Martín+krios@cnb.csic.es", 3) == "ana.mart_n_krios"
    assert storage.folderNameOf("..@example.com", 12) == "user12"
    assert storage.folderNameOf(None, 4) == "user4"


def test_SizesAreShownInGigabytes():
    assert storage.formatSize(None) is None
    assert storage.formatSize(3 * 1024 ** 3 // 2) == "1.50 GB"
