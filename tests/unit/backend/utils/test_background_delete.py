from app.backend.utils import background_delete as bg


def test_AFolderDisappearsAtOnceAndIsRemovedInTheBackground(tmp_path):
    folder = tmp_path / "Runs" / "000123_ProtBig"
    (folder / "extra").mkdir(parents=True)
    (folder / "extra" / "data.mrc").write_bytes(b"x" * 1024)

    bg.deleteInBackground(folder, trashIn=tmp_path)

    assert not folder.exists()
    assert not (tmp_path / "Runs" / bg.TRASH_FOLDER).exists()
    bg.waitForBackgroundDeletes(timeout=10)
    assert list((tmp_path / bg.TRASH_FOLDER).iterdir()) == []


def test_LeftoversOfAnEarlierRunAreRemoved(tmp_path):
    trash = tmp_path / bg.TRASH_FOLDER
    (trash / "old.abc").mkdir(parents=True)
    (trash / "old.abc" / "file").write_text("x")

    bg.purgeTrash(trash)
    bg.waitForBackgroundDeletes(timeout=10)

    assert list(trash.iterdir()) == []


def test_MissingPathsAreIgnored(tmp_path):
    assert bg.deleteInBackground(tmp_path / "nothing") is None


def test_the_current_folder_its_parents_home_and_root_are_never_deleted(tmp_path, monkeypatch):
    from app.backend.utils import background_delete

    project = tmp_path / "project"
    (project / "Runs" / "000002_ProtA").mkdir(parents=True)
    (project / "keep.txt").write_text("x")
    monkeypatch.chdir(project)

    for path in ("", ".", str(project), str(tmp_path), "/", str(project / "Runs" / "..")):
        assert background_delete.isUnsafeToDelete(path), path
        assert background_delete.deleteInBackground(path) is None
        background_delete.removeInBackground(path)
    background_delete.waitForBackgroundDeletes(timeout=10)
    assert (project / "keep.txt").exists() and (project / "Runs" / "000002_ProtA").is_dir()

    # A folder inside the current one is still deleted.
    assert not background_delete.isUnsafeToDelete("Runs/000002_ProtA")
    background_delete.deleteInBackground("Runs/000002_ProtA")
    background_delete.waitForBackgroundDeletes(timeout=10)
    assert not (project / "Runs" / "000002_ProtA").exists()


def test_ADeletedProjectsFolderMadeAgainByLateWorkIsALeftover(tmp_path):
    project = tmp_path / "Krios_DATA_01"
    for folder in ("Runs/000002_ProtImportMovies", "Logs", ".thumbnail_cache/v3/p13", bg.TRASH_FOLDER):
        (project / folder).mkdir(parents=True)
    (project / ".thumbnail_cache" / "v3" / "p13" / "movies.webp").write_bytes(b"x")
    assert bg.isLeftoverFolder(project)

    # A file of its own: a project (or anything else), never a leftover
    (project / "Logs" / "project.log").write_text("x")
    assert not bg.isLeftoverFolder(project)
    assert not bg.isLeftoverFolder(tmp_path / "missing")
    link = tmp_path / "link"
    link.symlink_to(tmp_path / "missing")
    assert not bg.isLeftoverFolder(link)
