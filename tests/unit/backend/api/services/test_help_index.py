"""The protocols' help is read once and again only when the plugins change."""
from app.backend.api.services import help_index


def test_read_once_per_plugins_revision(monkeypatch):
    revision = {"value": 1}
    reads = []

    def read():
        reads.append(revision["value"])
        return [{"className": "ProtA", "label": "a", "doc": "", "params": []}]

    monkeypatch.setattr(help_index, "getPluginsRevision", lambda: revision["value"])
    monkeypatch.setattr(help_index, "_cache", {"revision": None, "protocols": None})
    assert help_index.protocolsHelp(read)[0]["className"] == "ProtA"
    help_index.protocolsHelp(read)
    assert reads == [1]
    revision["value"] = 2
    help_index.protocolsHelp(read)
    assert reads == [1, 2]
    assert help_index.protocolHelp("ProtA", read)["label"] == "a"
    assert help_index.protocolHelp("ProtB", read) is None
