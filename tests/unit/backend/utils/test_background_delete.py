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
