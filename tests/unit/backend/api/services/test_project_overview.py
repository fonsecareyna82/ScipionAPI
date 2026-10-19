"""A project at a glance: runs by status and time, disk usage."""
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


def make_protocol(tmp_path, protocolId, cls, sizes):
    folder = overview.protocolFolder(str(tmp_path), protocolId, cls)
    (folder / "extra" / "sub").mkdir(parents=True)
    for index, size in enumerate(sizes):
        (folder / "extra" / "sub" / ("f%d" % index)).write_bytes(b"x" * size)
    return folder


def test_disk_usage_counts_each_protocol_folder_without_following_links(tmp_path):
    make_protocol(tmp_path, 1, "ProtA", [100, 50, 30])
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
    assert (first["protocolId"], first["bytes"], first["files"]) == ("1", 180, 3)
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
