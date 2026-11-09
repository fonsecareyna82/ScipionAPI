# ******************************************************************************
# *
# * Authors:     Yunior C. Fonseca Reyna
# *
# * Unidad de  Bioinformatica of Centro Nacional de Biotecnologia , CSIC
# *
# * This program is free software; you can redistribute it and/or modify
# * it under the terms of the GNU General Public License as published by
# * the Free Software Foundation; either version 3 of the License, or
# * (at your option) any later version.
# *
# * This program is distributed in the hope that it will be useful,
# * but WITHOUT ANY WARRANTY; without even the implied warranty of
# * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# * GNU General Public License for more details.
# *
# * You should have received a copy of the GNU General Public License
# * along with this program; if not, write to the Free Software
# * Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA
# * 02111-1307  USA
# *
# *  All comments concerning this program package may be sent to the
# *  e-mail address 'scipion@cnb.csic.es'
# *
# ******************************************************************************
"""The compute nodes of a multi-node installation.

Every node sees the same installation (the ScipionAPI folder, scipion_home and the conda environment) at the same
paths, on a shared disk. The main node runs the API, the database, Valkey and the plugin worker; a compute node
only runs a protocol worker, listening to its queue.

What is a node's own lives in its profile, scipion_home/nodes/<node>.env, read over the shared .env by every
command run on that node: its role, its queue, its concurrency and its log folder. Its PID files go to
.run/nodes/<node>/, so the main node never takes a node's worker for one of its own (with a shared .run, the API
would see a PID that is not running on its machine and start or remove it).
"""
import json
import os
import re
import socket
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from scipionapi_cli.envfile import readEnvFile, writeEnvFile

# Protocols the protocol worker of a machine runs at once (each one in streaming keeps its place all along)
DEFAULT_PROTOCOL_WORKER_CONCURRENCY = 12
NODES_FOLDER = "nodes"
NODE_ROLE_KEY = "SCIPIONAPI_NODE_ROLE"
MAIN_NODE_KEY = "SCIPIONAPI_MAIN_NODE"
DEPLOYMENT_MODE_KEY = "SCIPIONAPI_DEPLOYMENT_MODE"
DEFAULT_NODE_ROLE = "protocols"
# 0 on a main node that leaves the protocols to its compute nodes (`scipionapi multinode compute off`)
MAIN_COMPUTE_KEY = "SCIPIONAPI_MAIN_RUNS_PROTOCOLS"
DEFAULT_QUEUE = "protocols"

_NAME = re.compile(r"[^a-z0-9_-]+")


def nodeName(hostname: Optional[str] = None) -> str:
    """This machine's name as nodes know it: its short host name."""
    short = (hostname or socket.gethostname() or "node").split(".", 1)[0].strip().lower()
    return _NAME.sub("-", short).strip("-") or "node"


def profilePath(scipionHome: Path, name: Optional[str] = None) -> Path:
    return Path(scipionHome) / NODES_FOLDER / ("%s.env" % (name or nodeName()))


def readProfile(scipionHome: Path, name: Optional[str] = None) -> Dict[str, str]:
    """This node's profile ({} on the main node and on a single-node installation)."""
    path = profilePath(scipionHome, name)
    return readEnvFile(path) if path.is_file() else {}


def applyProfile(env: Dict[str, str], scipionHome: Path) -> Dict[str, str]:
    """The .env with this node's profile over it, the profile exported to the process too (workers inherit it)."""
    profile = readProfile(scipionHome)
    for key, value in profile.items():
        os.environ[key] = value
    return dict(env, **profile)


def runDirOf(repoRoot: Path, scipionHome: Path) -> Path:
    """Where this machine keeps its PID files: .run on the main node, .run/nodes/<node> on a compute node."""
    runDir = Path(repoRoot) / ".run"
    if readProfile(scipionHome):
        runDir = runDir / NODES_FOLDER / nodeName()
    runDir.mkdir(parents=True, exist_ok=True)
    return runDir


def roleOf(role: str, scipionHome: Path) -> str:
    """On a compute node, the default role (all) is the node's: the API never starts there."""
    profile = readProfile(scipionHome)
    if profile and role == "all":
        return (profile.get(NODE_ROLE_KEY) or DEFAULT_NODE_ROLE).strip().lower()
    return role


def mainRunsProtocols(scipionHome: Path, env: Optional[Dict[str, str]] = None) -> bool:
    """Whether this machine runs a protocol worker: a compute node always; the main node unless it was told not to."""
    if readProfile(scipionHome):
        return True
    value = ((env if env is not None else os.environ).get(MAIN_COMPUTE_KEY) or "1").strip().lower()
    return value not in ("0", "false", "no", "off")


def activeProtocols(workerName: str, timeoutSec: float = 3.0) -> Optional[int]:
    """How many protocols the worker runs now (None when it cannot be asked)."""
    try:
        from app.workers.task_queue import celeryApp

        active = celeryApp.control.inspect(destination=[workerName], timeout=timeoutSec).active()
    except Exception:
        return None
    if active is None:
        return 0
    return len(active.get(workerName) or [])


def listProfiles(scipionHome: Path) -> List[Tuple[str, Dict[str, str]]]:
    folder = Path(scipionHome) / NODES_FOLDER
    if not folder.is_dir():
        return []
    return [(path.stem, readEnvFile(path)) for path in sorted(folder.glob("*.env"))]


def profileValues(scipionHome: Path, name: str, queue: str, concurrency: int) -> Dict[str, str]:
    return {
        NODE_ROLE_KEY: DEFAULT_NODE_ROLE,
        "PROTOCOLS_CELERY_QUEUE": queue,
        "PROTOCOL_WORKER_CONCURRENCY": str(int(concurrency)),
        # Each node logs apart, in the shared logs folder
        "LOGS_PATH": str(Path(scipionHome) / "logs" / NODES_FOLDER / name),
    }


# Which protocols go to a node's queue --------------------------------------------------------------------------

ROUTING_FILE = "celery_queue_routing.json"


def ensureScipionHost(scipionHome: Path, host: str) -> bool:
    """A Scipion host (hosts.conf) of this name, as a copy of localhost when there is none; True when made.

    The users pick it in a protocol's form (its host) to run it on the nodes of its queue.
    """
    path = Path(scipionHome) / "config" / "hosts.conf"
    text = path.read_text() if path.is_file() else ""
    if host in re.findall(r"^\[([^\]]+)\]\s*$", text, flags=re.M):
        return False
    local = re.search(r"^\[localhost\]\s*\n(.*?)(?=^\[|\Z)", text, flags=re.M | re.S)
    body = local.group(1).rstrip("\n") + "\n" if local else ""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip("\n") + ("\n\n" if text.strip() else "") + "[%s]\n%s" % (host, body))
    return True


def routeHostToQueue(scipionHome: Path, host: str, queue: str) -> None:
    """Protocols run on the Scipion host go to this queue (scipion_home/config/celery_queue_routing.json)."""
    path = Path(scipionHome) / "config" / ROUTING_FILE
    try:
        routing = json.loads(path.read_text()) if path.is_file() else {}
    except ValueError:
        routing = {}
    if not isinstance(routing, dict):
        routing = {}
    routing[host] = queue
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(routing, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


# Joining ---------------------------------------------------------------------------------------------------------

class Check:
    def __init__(self, label: str, ok: bool, detail: str, required: bool = True):
        self.label, self.ok, self.detail, self.required = label, ok, detail, required


def _writable(folder: Path) -> Tuple[bool, str]:
    if not folder.is_dir():
        return False, "not found here: %s (it must be on the shared disk, at the same path as on the main node)" \
            % folder
    probe = folder / (".scipionweb-node-%s-%d" % (nodeName(), os.getpid()))
    try:
        probe.write_text("probe")
        probe.unlink()
    except OSError as error:
        return False, "not writable from this node: %s (%s)" % (folder, error.strerror or error)
    return True, str(folder)


def checkDatabase(env: Dict[str, str]) -> Tuple[bool, str]:
    host = (env.get("POSTGRES_HOST") or "localhost").strip()
    port = (env.get("POSTGRES_PORT") or "5432").strip()
    try:
        import psycopg2

        connection = psycopg2.connect(dbname=env.get("DATABASE_NAME"), user=env.get("DATABASE_USER"),
                                      password=env.get("DATABASE_PASS"), host=host, port=port, connect_timeout=5)
        connection.close()
    except Exception as error:
        return False, "%s:%s could not be reached: %s" % (host, port, str(error).strip().splitlines()[0])
    return True, "%s:%s" % (host, port)


def checkBroker(env: Dict[str, str]) -> Tuple[bool, str]:
    url = (env.get("BROKER_URL") or "").strip()
    if not url:
        return False, "BROKER_URL is missing"
    from urllib.parse import urlparse

    where = "%s:%s" % (urlparse(url).hostname, urlparse(url).port or 6379)
    try:
        import redis

        client = redis.Redis.from_url(url, socket_connect_timeout=5, socket_timeout=5)
        client.ping()
        client.close()
    except Exception as error:
        return False, "%s could not be reached: %s" % (where, error)
    return True, where


def gpuCount() -> Optional[int]:
    import shutil
    import subprocess

    if not shutil.which("nvidia-smi"):
        return None
    try:
        result = subprocess.run(["nvidia-smi", "-L"], capture_output=True, text=True, timeout=10)
    except Exception:
        return None
    return sum(1 for line in result.stdout.splitlines() if line.startswith("GPU ")) if result.returncode == 0 \
        else None


def joinChecks(repoRoot: Path, scipionHome: Path, env: Dict[str, str],
               database: Optional[Callable[[Dict[str, str]], Tuple[bool, str]]] = None,
               broker: Optional[Callable[[Dict[str, str]], Tuple[bool, str]]] = None) -> List[Check]:
    """Whether this machine can be a compute node of the installation."""
    database = database or checkDatabase
    broker = broker or checkBroker
    checks = []
    mode = (env.get(DEPLOYMENT_MODE_KEY) or "single-node").strip().lower()
    checks.append(Check("Multi-node installation", mode == "multi-node",
                        "yes" if mode == "multi-node" else
                        "not yet: run 'scipionapi multinode enable --network <the nodes' network>' on the main "
                        "node first"))
    main = (env.get(MAIN_NODE_KEY) or "").strip()
    checks.append(Check("Not the main node", nodeName() != main,
                        "this machine is %s, the main node is %s" % (nodeName(), main or "unknown")
                        if nodeName() != main else "this is the main node (%s): it already runs everything" % main))
    for label, folder in (("Installation folder", repoRoot), ("SCIPION_HOME", scipionHome),
                          ("Projects folder", Path(env.get("PROJECTS_PATH") or scipionHome / "projects"))):
        ok, detail = _writable(Path(folder))
        checks.append(Check(label, ok, detail))
    try:
        owner = Path(scipionHome).stat().st_uid
        sameUser = owner == os.getuid()
        checks.append(Check("Same user as the main node", sameUser,
                            "uid %d" % owner if sameUser else
                            "SCIPION_HOME belongs to uid %d and this is uid %d: run as the installation's user, "
                            "with the same uid on every node" % (owner, os.getuid())))
    except OSError:
        pass
    ok, detail = database(env)
    checks.append(Check("Database (from this node)", ok, detail))
    ok, detail = broker(env)
    checks.append(Check("Valkey (from this node)", ok, detail))
    gpus = gpuCount()
    checks.append(Check("GPUs", True, "none found (nvidia-smi)" if not gpus else "%d" % gpus, required=False))
    return checks


def joinNode(repoRoot: Path, scipionHome: Path, env: Dict[str, str], queue: Optional[str],
             concurrency: Optional[int], printCheck: Callable[[Check], None],
             start: Callable[[], None], scipionHost: Optional[str] = None) -> bool:
    """Make this machine a compute node: check it, write its profile and start its protocol worker.

    With scipionHost, the protocols run on that Scipion host (made as a copy of localhost if needed) go to the
    node's queue.
    """
    checks = joinChecks(repoRoot, scipionHome, env)
    for check in checks:
        printCheck(check)
    if not all(check.ok for check in checks if check.required):
        return False
    name = nodeName()
    values = profileValues(scipionHome, name, (queue or DEFAULT_QUEUE).strip() or DEFAULT_QUEUE,
                           concurrency or DEFAULT_PROTOCOL_WORKER_CONCURRENCY)
    path = profilePath(scipionHome, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    writeEnvFile(path, values)
    Path(values["LOGS_PATH"]).mkdir(parents=True, exist_ok=True)
    if scipionHost:
        ensureScipionHost(scipionHome, scipionHost.strip())
        routeHostToQueue(scipionHome, scipionHost.strip(), values["PROTOCOLS_CELERY_QUEUE"])
    start()
    return True


def leaveNode(scipionHome: Path, stop: Callable[[], None]) -> bool:
    """Stop this node's worker and forget its profile; False when this machine is not a node."""
    path = profilePath(scipionHome)
    if not path.is_file():
        return False
    stop()
    # Its PIDs and logs stay until the next join (they are small, and the logs may be wanted)
    path.unlink()
    return True


def liveWorkers(timeoutSec: float = 2.0) -> Dict[str, List[str]]:
    """The Celery workers answering now, by host name, with their queues (empty when none answers)."""
    try:
        from app.workers.task_queue import celeryApp
    except Exception:
        return {}
    try:
        inspect = celeryApp.control.inspect(timeout=timeoutSec)
        active = inspect.active_queues() or {}
    except Exception:
        return {}
    return {worker: sorted(queue.get("name", "") for queue in queues or []) for worker, queues in active.items()}


def waitForWorker(name: str, timeoutSec: float = 20.0) -> bool:
    deadline = time.monotonic() + timeoutSec
    while time.monotonic() < deadline:
        if any(worker.split("@", 1)[-1].split(".", 1)[0].lower() == name for worker in liveWorkers()):
            return True
        time.sleep(2)
    return False
