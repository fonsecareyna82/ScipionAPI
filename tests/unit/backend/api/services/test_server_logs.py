import pytest

from app.backend.api.services.server_logs import logPath, readLog, redact


def test_PrivateValuesAreBlottedOut():
    text = redact("login ana.pi@cnb.csic.es password=hunter2 token: abc.def Authorization: Bearer xyz.123 "
                  "key AIzaSyA1234567890abcdef and sk-proj-abcdefghijklmnop "
                  + "a" * 45 + " path /data/projects/SPA/Runs/000022_extract")
    for secret in ("ana.pi@cnb.csic.es", "hunter2", "abc.def", "xyz.123", "AIzaSyA1234567890abcdef",
                   "sk-proj-abcdefghijklmnop", "a" * 45):
        assert secret not in text
    assert "/data/projects/SPA/Runs/000022_extract" in text


def test_OnlyTheKnownLogsAndNodes(tmp_path):
    assert logPath("api", folder=tmp_path) == tmp_path / "app.log"
    assert logPath("protocols-worker", "node2", folder=tmp_path) == tmp_path / "nodes" / "node2" / "celery-protocols.log"
    with pytest.raises(ValueError):
        logPath("../../etc/passwd", folder=tmp_path)
    with pytest.raises(ValueError):
        logPath("api", "../x", folder=tmp_path)


def test_TheEndOrTheLinesSearched(tmp_path):
    (tmp_path / "celery.log").write_text("start\n" + "".join("line %d ok\n" % i for i in range(5))
                                         + "worker error: lost connection, mail root@host.org\n")
    end = readLog("plugins-worker", folder=tmp_path)
    assert end["log"] == "plugins-worker" and "lost connection" in end["text"] and "root@host.org" not in end["text"]
    found = readLog("plugins-worker", search="ERROR worker", folder=tmp_path)
    assert found["text"].startswith("worker error") and "line 1" not in found["text"]
    assert readLog("plugins-worker", search="nothing", folder=tmp_path)["text"] == "(no line has those words)"


def test_AMissingLogNamesTheNodesThereAre(tmp_path):
    (tmp_path / "nodes" / "gpu02").mkdir(parents=True)
    with pytest.raises(ValueError) as error:
        readLog("protocols-worker", "gpu01", folder=tmp_path)
    assert "gpu02" in str(error.value)


def test_TheLogToolOnlyForAdministrators():
    import json

    from app.backend.api.services.assistant_agent import AssistantAgent, AssistantTools

    read = [lambda: [], lambda p: [], lambda p, q: None, lambda p, q, c: "", lambda p, q: {}, lambda q: []]

    class Model:
        def chat(self, messages, tools=None):
            self.messages, self.tools = messages, tools
            return {"message": {"content": "ok"}, "usage": {"inputTokens": 1, "outputTokens": 1}}

    for admin in (False, True):
        model = Model()
        tools = AssistantTools(*read, serverLog=(lambda which, node, search: {}) if admin else None)
        AssistantAgent(model, tools).answer("why is the worker down?", "")
        assert ("server_log" in {tool["function"]["name"] for tool in model.tools}) is admin
        assert ("This user runs the installation" in model.messages[0]["content"]) is admin
