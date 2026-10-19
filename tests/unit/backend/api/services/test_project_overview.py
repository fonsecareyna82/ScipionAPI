"""A project at a glance: runs by status and time, disk usage, emptying tmp folders."""
from datetime import datetime, timedelta, timezone

import pytest

from app.backend.api.services import project_overview as overview

NOW = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)


class Db:
    def __init__(self, rows):
        self.rows = rows

    def fetchAll(self, query, params):
        return self.rows


class Mapper:
    def __init__(self, rows):
        self.db = Db(rows)


def run(protocolId, status, start=None, end=None, cls="ProtA", label=None):
    return {"protocolId": protocolId, "protocolClassName": cls, "status": status, "label": label or "run %s" % protocolId,
            "updatedAt": end or start, "startedAt": start, "endedAt": end, "stepCount": 4, "stepsDone": 2}


def test_runs_are_counted_by_status_and_listed_newest_first():
    rows = [
        run("1", "finished", NOW - timedelta(hours=3), NOW - timedelta(hours=2)),
        run("2", "finished", NOW - timedelta(hours=2), NOW - timedelta(minutes=50)),
        run("3", "failed", NOW - timedelta(hours=1), NOW - timedelta(minutes=30)),
        run("4", "running", NOW - timedelta(minutes=10)),
        run("5", "new"),
    ]
    payload = overview.projectOverview(Mapper(rows), 7, now=NOW)
    assert payload["protocols"] == 5
    assert payload["counts"] == {"finished": 2, "failed": 1, "running": 1, "new": 1}
    assert [item["protocolId"] for item in payload["recent"]] == ["2", "1"]
    assert [item["protocolId"] for item in payload["failed"]] == ["3"]
    running = payload["running"][0]
    assert running["protocolId"] == "4" and running["endedAt"] is None and running["seconds"] == 600
    # Only runs that ended add to the compute time: 1 h + 70 min + 30 min.
    assert payload["computeSeconds"] == 3600 + 4200 + 1800
    assert [item["protocolId"] for item in payload["longest"]] == ["2", "1", "3"]
    assert all("_sortEnd" not in item for item in payload["recent"])


def make_protocol(tmp_path, protocolId, cls, sizes, tmpSizes=()):
    folder = overview.protocolFolder(str(tmp_path), protocolId, cls)
    (folder / "extra").mkdir(parents=True)
    for index, size in enumerate(sizes):
        (folder / "extra" / ("f%d" % index)).write_bytes(b"x" * size)
    if tmpSizes:
        (folder / "tmp" / "sub").mkdir(parents=True)
        for index, size in enumerate(tmpSizes):
            (folder / "tmp" / "sub" / ("t%d" % index)).write_bytes(b"x" * size)
    return folder


def test_disk_usage_counts_each_protocol_folder_without_following_links(tmp_path):
    make_protocol(tmp_path, 1, "ProtA", [100, 50], tmpSizes=[30])
    second = make_protocol(tmp_path, 2, "ProtB", [10])
    (second / "extra" / "link").symlink_to(tmp_path / "Runs")
    cache = overview.DiskUsageCache()
    protocols = [{"protocolId": "1", "protocolClassName": "ProtA", "status": "finished"},
                 {"protocolId": "2", "protocolClassName": "ProtB", "status": "running"},
                 {"protocolId": "3", "protocolClassName": "Gone", "status": "new"}]
    payload = cache.get(7, str(tmp_path), protocols, background=False)
    assert payload["computing"] is False and payload["computedAt"]
    assert payload["totalBytes"] == 190
    first, other = payload["protocols"]
    assert (first["protocolId"], first["bytes"], first["files"], first["tmpBytes"]) == ("1", 180, 3, 30)
    assert (other["protocolId"], other["bytes"]) == ("2", 10)

    # A recent count is reused; refresh counts again.
    (tmp_path / "Runs" / "000002_ProtB" / "extra" / "big").write_bytes(b"x" * 1000)
    assert cache.get(7, str(tmp_path), protocols, background=False)["totalBytes"] == 190
    assert cache.get(7, str(tmp_path), protocols, refresh=True, background=False)["totalBytes"] == 1190


def test_a_project_not_counted_yet_says_it_is_being_counted(tmp_path):
    cache = overview.DiskUsageCache()
    cache._running[7] = object()
    payload = cache.get(7, str(tmp_path), [], background=False)
    assert payload == {"computedAt": None, "totalBytes": None, "protocols": [], "computing": True}


def test_the_tmp_folder_of_a_finished_protocol_is_emptied(tmp_path):
    folder = make_protocol(tmp_path, 4, "ProtA", [100], tmpSizes=[30, 20])
    (folder / "tmp" / "top.mrc").write_bytes(b"x" * 5)
    result = overview.cleanProtocolTmp(str(tmp_path), {"protocolId": "4", "protocolClassName": "ProtA", "status": "finished"})
    assert result == {"freedBytes": 55, "removedFiles": 3}
    assert (folder / "tmp").is_dir() and not any((folder / "tmp").iterdir())
    assert (folder / "extra" / "f0").exists()


@pytest.mark.parametrize("status", ["running", "launched", "failed", "interactive", "scheduled"])
def test_the_tmp_folder_of_an_unfinished_protocol_is_kept(tmp_path, status):
    folder = make_protocol(tmp_path, 5, "ProtA", [1], tmpSizes=[10])
    with pytest.raises(overview.CleanTmpRefused):
        overview.cleanProtocolTmp(str(tmp_path), {"protocolId": "5", "protocolClassName": "ProtA", "status": status})
    assert (folder / "tmp" / "sub" / "t0").exists()


def test_a_tmp_folder_that_is_a_link_is_not_followed(tmp_path):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "keep").write_bytes(b"x")
    folder = make_protocol(tmp_path, 6, "ProtA", [1])
    (folder / "tmp").symlink_to(elsewhere)
    result = overview.cleanProtocolTmp(str(tmp_path), {"protocolId": "6", "protocolClassName": "ProtA", "status": "finished"})
    assert result == {"freedBytes": 0, "removedFiles": 0}
    assert (elsewhere / "keep").exists()


def test_forgetting_a_tmp_folder_updates_the_cached_count(tmp_path):
    make_protocol(tmp_path, 1, "ProtA", [100], tmpSizes=[30])
    cache = overview.DiskUsageCache()
    protocols = [{"protocolId": "1", "protocolClassName": "ProtA", "status": "finished"}]
    cache.get(7, str(tmp_path), protocols, background=False)
    cache.forget(7, "1")
    payload = cache.get(7, str(tmp_path), protocols, background=False)
    assert payload["totalBytes"] == 100 and payload["protocols"][0]["tmpBytes"] == 0
