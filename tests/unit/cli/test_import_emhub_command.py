"""The import-emhub command: only shows what it would do unless --apply, and says what it did."""
from types import SimpleNamespace

from typer.testing import CliRunner

from scipionapi_cli import cli, runtime
from app.backend.importers import emhub

REPORT = {"users": [{"action": "create"}, {"action": "match"}], "groups": [{"action": "create"}],
          "resources": [], "bookings": [{"action": "create"}], "sessions": [],
          "skipped": [{"kind": "booking", "id": 5, "why": "no valid times"}],
          "staffRoles": [{"email": "mikel@example.org", "roles": ["manager"]}], "countedOnly": {"applications": 3}}


class FakeDb:
    def __init__(self):
        self.calls = []

    def rollback(self):
        self.calls.append("rollback")

    def close(self):
        self.calls.append("close")


def test_ItShowsWhatItWouldDoAndWritesOnlyWithApply(monkeypatch, tmp_path):
    db = FakeDb()
    calls = []
    monkeypatch.setattr(runtime, "_loadEnv", lambda root: {})
    # The real module needs the installation's database: a stand-in that answers the fake one
    import sys

    monkeypatch.setitem(sys.modules, "app.backend.database", SimpleNamespace(getMapper=lambda: SimpleNamespace(db=db)))
    monkeypatch.setattr(emhub, "readEmhub", lambda path: {"users": []})
    monkeypatch.setattr(emhub, "plan", lambda data, mapper, withSessions=False, since=None: calls.append(("plan", withSessions, since)) or REPORT)
    monkeypatch.setattr(emhub, "apply", lambda data, db, withSessions=False, since=None: calls.append(("apply", withSessions, since)) or REPORT)
    file = tmp_path / "emhub.sqlite"
    file.write_text("")

    shown = CliRunner().invoke(cli.app, ["import-emhub", str(file), "--details"])

    assert shown.exit_code == 0, shown.output
    assert "nothing written" in shown.output and "users      create 1, match 1" in shown.output
    assert "left out booking 5: no valid times" in shown.output and "staff mikel@example.org: manager" in shown.output
    assert calls == [("plan", False, None)] and db.calls == ["rollback", "close"]

    done = CliRunner().invoke(cli.app, ["import-emhub", str(file), "--apply", "--with-sessions", "--since", "2025-01-01"])

    assert done.exit_code == 0, done.output
    assert done.output.startswith("Imported:")
    assert calls[-1][0] == "apply" and calls[-1][1] is True and str(calls[-1][2]) == "2025-01-01"
