"""Opening the main node to compute nodes, and the nodes' own profiles."""
import os
import subprocess
from pathlib import Path

import pytest

from scipionapi_cli import multinode, nodes
from scipionapi_cli.envfile import readEnvFile


# What changes, as text ------------------------------------------------------------------------------------------

def test_TheNodesNetworkGetsOneLineInPgHba():
    line = multinode.hbaLine("scipion_db", "scipion_user", "10.0.0.0/24", "scram-sha-256")
    content = "local   all   postgres   peer\nhost    all   all   127.0.0.1/32   scram-sha-256\n"

    updated, changed = multinode.withHbaLine(content, line)
    assert changed and updated.endswith(line + "\n") and updated.startswith(content)

    again, changedAgain = multinode.withHbaLine(updated, line)
    assert again == updated and not changedAgain


def test_ValkeyListensOnTheNetworkWithAPassword():
    content = "port 6379\nbind 127.0.0.1 -::1\nprotected-mode yes\n# requirepass foobared\n"

    updated = multinode.valkeyConfig(content, "s3cret")

    lines = updated.splitlines()
    assert "port 6379" in lines and "protected-mode yes" in lines
    assert "bind %s" % multinode.VALKEY_BIND in lines and "requirepass s3cret" in lines
    # The old bind is kept, commented out, and only one is active
    assert [line for line in lines if line.startswith("bind ")] == ["bind %s" % multinode.VALKEY_BIND]
    assert multinode.valkeyPassword(updated) == "s3cret"
    assert multinode.valkeyPassword(content) is None


def test_TheEnvNamesTheMainNodeInsteadOfLocalhost():
    env = {"POSTGRES_HOST": "localhost", "DATABASE_URL": "postgresql+psycopg2://user:p%40ss@localhost:5432/db",
           "BROKER_URL": "redis://localhost:6379/0", "RESULT_BACKEND_URL": "redis://127.0.0.1:6379/1"}

    updates = multinode.envUpdates(env, "krios-server.cnb.csic.es", "10.0.0.0/24", "va/lk", "krios-server")

    assert updates["POSTGRES_HOST"] == "krios-server.cnb.csic.es"
    assert updates["DATABASE_URL"] == "postgresql+psycopg2://user:p%40ss@krios-server.cnb.csic.es:5432/db"
    assert updates["BROKER_URL"] == "redis://:va%2Flk@krios-server.cnb.csic.es:6379/0"
    assert updates["RESULT_BACKEND_URL"] == "redis://:va%2Flk@krios-server.cnb.csic.es:6379/1"
    assert updates[nodes.DEPLOYMENT_MODE_KEY] == "multi-node" and updates[nodes.MAIN_NODE_KEY] == "krios-server"
    # A database elsewhere is left as it is
    assert "POSTGRES_HOST" not in multinode.envUpdates(dict(env, POSTGRES_HOST="db.cnb.csic.es"), "h", "n", None, "m")


def test_TheNetworkMustBeOne():
    assert multinode.checkNetwork("10.0.0.7/24") == "10.0.0.0/24"
    for wrong in ("0.0.0.0/0", "krios", "10.0.0.0/33"):
        with pytest.raises(ValueError):
            multinode.checkNetwork(wrong)


# The plan, with the system commands faked -----------------------------------------------------------------------

class FakeRunner(multinode.Runner):
    def __init__(self, files):
        self.files, self.commands = files, []

    def run(self, command, sudo=False, inputText=None, check=True):
        self.commands.append((command, sudo))
        out = ""
        if command[:3] == ["sudo", "-u", "postgres"]:
            out = {"SHOW hba_file": "/etc/pg/pg_hba.conf", "SHOW password_encryption": "scram-sha-256",
                   "SHOW listen_addresses": "localhost"}.get(command[-1], "")
        elif command[0] == "valkey-cli":
            out = "redis_version:7.2\nconfig_file:/etc/valkey/valkey.conf\n"
        elif command[0] == "cat":
            out = self.files[command[1]]
        elif command[0] == "tee":
            self.files[command[1]] = inputText
        elif command[0] == "cp":
            Path(command[3]).write_text(self.files[command[2]])
        elif command[0] == "systemctl" and command[1] == "list-unit-files":
            out = "postgresql.service enabled\nvalkey-server.service enabled\n"
        elif command[0] == "ufw" and command[1] == "status":
            out = "Status: active\n"
        return subprocess.CompletedProcess(command, 0, out, "")


def test_EnablingOpensTheDatabaseValkeyTheFirewallAndTheEnvBackingThemUp(tmp_path):
    scipionHome = tmp_path / "scipion_home"
    scipionHome.mkdir()
    envPath = scipionHome / ".env"
    envPath.write_text("DATABASE_NAME=db\nDATABASE_USER=user\nPOSTGRES_HOST=localhost\n"
                       "BROKER_URL=redis://localhost:6379/0\n")
    runner = FakeRunner({"/etc/pg/pg_hba.conf": "local all postgres peer\n",
                         "/etc/valkey/valkey.conf": "port 6379\nbind 127.0.0.1 -::1\n"})
    restarted = []

    steps, warnings = multinode.buildPlan(readEnvFile(envPath), envPath, scipionHome, "10.0.0.0/24", "main.lab",
                                          runner, restart=lambda: restarted.append(True))
    assert warnings == []
    for step in steps:
        step.action()

    assert "10.0.0.0/24" in runner.files["/etc/pg/pg_hba.conf"] and multinode.MARKER in \
        runner.files["/etc/pg/pg_hba.conf"]
    assert (["sudo", "-u", "postgres", "psql", "-d", "postgres", "-tAc", "ALTER SYSTEM SET listen_addresses = '*'"],
            False) in runner.commands
    password = multinode.valkeyPassword(runner.files["/etc/valkey/valkey.conf"])
    assert password and len(password) >= 20
    assert (["systemctl", "restart", "postgresql"], True) in runner.commands
    assert (["systemctl", "restart", "valkey-server"], True) in runner.commands
    assert (["ufw", "allow", "from", "10.0.0.0/24", "to", "any", "port", "6379", "proto", "tcp"], True) \
        in runner.commands

    env = readEnvFile(envPath)
    assert env["POSTGRES_HOST"] == "main.lab" and env["BROKER_URL"] == "redis://:%s@main.lab:6379/0" % password
    assert env[nodes.DEPLOYMENT_MODE_KEY] == "multi-node"
    backups = list((scipionHome / "multinode").iterdir())
    assert len(backups) == 1
    assert sorted(path.name for path in backups[0].iterdir()) == [".env", "pg_hba.conf", "valkey.conf"]
    assert "localhost" in (backups[0] / ".env").read_text()
    assert restarted == [True]


# The nodes' profiles --------------------------------------------------------------------------------------------

def test_ANodeHasItsOwnProfilePidsAndRole(tmp_path, monkeypatch):
    monkeypatch.setattr(nodes.socket, "gethostname", lambda: "gpu-node-1.cnb.csic.es")
    repoRoot, scipionHome = tmp_path / "api", tmp_path / "api" / "scipion_home"
    scipionHome.mkdir(parents=True)

    # The main node (no profile): .run, every role
    assert nodes.runDirOf(repoRoot, scipionHome) == repoRoot / ".run"
    assert nodes.roleOf("all", scipionHome) == "all"

    path = nodes.profilePath(scipionHome)
    path.parent.mkdir()
    path.write_text("SCIPIONAPI_NODE_ROLE=protocols\nPROTOCOLS_CELERY_QUEUE=protocols-gpu\n")
    monkeypatch.delenv("PROTOCOLS_CELERY_QUEUE", raising=False)

    assert path.name == "gpu-node-1.env"
    assert nodes.runDirOf(repoRoot, scipionHome) == repoRoot / ".run" / "nodes" / "gpu-node-1"
    assert nodes.roleOf("all", scipionHome) == "protocols" and nodes.roleOf("plugins", scipionHome) == "plugins"
    merged = nodes.applyProfile({"PROTOCOLS_CELERY_QUEUE": "protocols", "BROKER_URL": "redis://main"}, scipionHome)
    assert merged == {"PROTOCOLS_CELERY_QUEUE": "protocols-gpu", "BROKER_URL": "redis://main",
                      "SCIPIONAPI_NODE_ROLE": "protocols"}
    assert os.environ["PROTOCOLS_CELERY_QUEUE"] == "protocols-gpu"


def test_AMachineJoinsOnlyWhenItSeesTheInstallationAndReachesTheMainNode(tmp_path, monkeypatch):
    monkeypatch.setattr(nodes.socket, "gethostname", lambda: "gpu-node-1")
    monkeypatch.setattr(nodes, "gpuCount", lambda: 2)
    repoRoot, scipionHome = tmp_path / "api", tmp_path / "api" / "scipion_home"
    (scipionHome / "projects").mkdir(parents=True)
    env = {nodes.DEPLOYMENT_MODE_KEY: "multi-node", nodes.MAIN_NODE_KEY: "main",
           "PROJECTS_PATH": str(scipionHome / "projects")}
    reached = lambda env: (True, "main:5432")
    started, printed = [], []

    checks = nodes.joinChecks(repoRoot, scipionHome, dict(env, **{nodes.DEPLOYMENT_MODE_KEY: "single-node"}),
                              database=reached, broker=reached)
    assert not next(check for check in checks if check.label == "Multi-node installation").ok
    checks = nodes.joinChecks(repoRoot, scipionHome, dict(env, PROJECTS_PATH=str(tmp_path / "elsewhere")),
                              database=reached, broker=lambda env: (False, "main:6379 could not be reached"))
    failed = {check.label for check in checks if not check.ok}
    assert failed == {"Projects folder", "Valkey (from this node)"}

    monkeypatch.setattr(nodes, "checkDatabase", reached)
    monkeypatch.setattr(nodes, "checkBroker", reached)
    assert nodes.joinNode(repoRoot, scipionHome, env, "protocols-gpu", None, printed.append,
                          start=lambda: started.append(True))
    profile = readEnvFile(nodes.profilePath(scipionHome))
    assert profile == {"SCIPIONAPI_NODE_ROLE": "protocols", "PROTOCOLS_CELERY_QUEUE": "protocols-gpu",
                       "PROTOCOL_WORKER_CONCURRENCY": "2",
                       "LOGS_PATH": str(scipionHome / "logs" / "nodes" / "gpu-node-1")}
    assert started == [True] and printed

    stopped = []
    assert nodes.leaveNode(scipionHome, stop=lambda: stopped.append(True)) and stopped == [True]
    assert not nodes.profilePath(scipionHome).exists()
    assert not nodes.leaveNode(scipionHome, stop=lambda: None)


def test_TheMainNodeDoesNotJoinItself(tmp_path, monkeypatch):
    monkeypatch.setattr(nodes.socket, "gethostname", lambda: "main")
    scipionHome = tmp_path / "scipion_home"
    (scipionHome / "projects").mkdir(parents=True)
    checks = nodes.joinChecks(tmp_path, scipionHome, {nodes.DEPLOYMENT_MODE_KEY: "multi-node",
                                                      nodes.MAIN_NODE_KEY: "main"},
                              database=lambda env: (True, ""), broker=lambda env: (True, ""))
    assert not next(check for check in checks if check.label == "Not the main node").ok


def test_AGpuNodeGetsItsScipionHostAndItsQueueRoute(tmp_path):
    scipionHome = tmp_path / "scipion_home"
    (scipionHome / "config").mkdir(parents=True)
    hosts = scipionHome / "config" / "hosts.conf"
    hosts.write_text("[localhost]\nPARALLEL_COMMAND = mpirun -np %_(JOB_NODES)d %_(COMMAND)s\nSUBMIT_TEMPLATE = #!/bin/bash\n"
                     "\t%_(JOB_COMMAND)s\n")

    assert nodes.ensureScipionHost(scipionHome, "gpu-nodes")
    assert not nodes.ensureScipionHost(scipionHome, "gpu-nodes")
    import configparser

    parser = configparser.RawConfigParser()
    parser.read(hosts)
    assert parser.sections() == ["localhost", "gpu-nodes"]
    assert dict(parser["gpu-nodes"]) == dict(parser["localhost"])

    nodes.routeHostToQueue(scipionHome, "gpu-nodes", "protocols-gpu")
    nodes.routeHostToQueue(scipionHome, "cpu-nodes", "protocols-cpu")
    from app.backend.runtime.celery_queue_routing_service import resolveCeleryQueueForHost

    assert resolveCeleryQueueForHost(str(scipionHome), "gpu-nodes") == "protocols-gpu"
    assert resolveCeleryQueueForHost(str(scipionHome), "cpu-nodes") == "protocols-cpu"
    assert resolveCeleryQueueForHost(str(scipionHome), "localhost") is None
