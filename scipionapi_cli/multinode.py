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
"""Open the main node of an installation to its compute nodes (`scipionapi multinode enable`).

The nodes reach the main node's database and Valkey over the network, so:
- PostgreSQL listens on the network and lets the installation's user in from the nodes' network only
  (one pg_hba.conf line, marked);
- Valkey listens on the network and asks for a password (a new one, unless it had one);
- the firewall (ufw, when it is active) lets the nodes' network reach both ports;
- the .env names the main node by its network name instead of localhost (the nodes read the same .env) and says
  the installation is multi-node.

Every file changed is copied first to scipion_home/multinode/backup-<time>/, and --dry-run shows the plan without
changing anything. The database and Valkey are only configured when they run on this machine.
"""
import ipaddress
import os
import secrets
import shlex
import socket
import subprocess
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple
from urllib.parse import quote, unquote, urlparse, urlunparse

from scipionapi_cli import nodes
from scipionapi_cli.envfile import readEnvFile, writeEnvFile

MARKER = "# ScipionWeb multi-node"
NETWORK_KEY = "SCIPIONAPI_MULTINODE_NETWORK"
LOOPBACK_HOSTS = {"", "localhost", "127.0.0.1", "::1", "0.0.0.0"}
VALKEY_BIND = "0.0.0.0 -::1"


class Runner:
    """Runs the system commands (with sudo when asked); the tests give a fake one."""

    def run(self, command: List[str], sudo: bool = False, inputText: Optional[str] = None,
            check: bool = True) -> subprocess.CompletedProcess:
        full = (["sudo"] + command) if sudo and os.geteuid() != 0 else command
        result = subprocess.run(full, input=inputText, capture_output=True, text=True)
        if check and result.returncode != 0:
            raise RuntimeError("%s failed: %s" % (" ".join(shlex.quote(part) for part in full),
                                                  (result.stderr or result.stdout).strip()))
        return result


# What changes, as text (pure, tested) -----------------------------------------------------------------------------

def hbaLine(database: str, user: str, network: str, method: str) -> str:
    return "host    %s    %s    %s    %s    %s" % (database, user, network, method, MARKER)


def withHbaLine(content: str, line: str) -> Tuple[str, bool]:
    """pg_hba.conf with the nodes' line (once); and whether it changed."""
    wanted = line.split(MARKER)[0].split()
    for existing in content.splitlines():
        if existing.split("#")[0].split() == wanted:
            return content, False
    return content.rstrip("\n") + "\n" + line + "\n", True


def valkeyConfig(content: str, password: str) -> str:
    """valkey.conf listening on the network with a password (other lines kept; the old ones commented out)."""
    lines = []
    for line in content.splitlines():
        words = line.split()
        if words and words[0].lower() in ("bind", "requirepass"):
            lines.append("# %s  %s" % (line, MARKER))
        else:
            lines.append(line)
    lines += ["", MARKER, "bind %s" % VALKEY_BIND, "requirepass %s" % password, ""]
    return "\n".join(lines)


def valkeyPassword(content: str) -> Optional[str]:
    """The password valkey.conf already asks for, if any."""
    for line in content.splitlines():
        words = line.split(None, 1)
        if len(words) == 2 and words[0].lower() == "requirepass":
            return words[1].strip().strip('"')
    return None


def withHost(url: str, host: str, password: Optional[str] = None) -> str:
    """The URL pointing to host (and with a password, for Valkey's), the rest kept."""
    parsed = urlparse(url)
    # The URL keeps them encoded: decoded here, encoded once again below
    user = unquote(parsed.username or "")
    secret = unquote(parsed.password or "") if password is None else password
    auth = ""
    if user or secret:
        auth = quote(user, safe="") + (":" + quote(secret, safe="") if secret else "") + "@"
    port = ":%d" % parsed.port if parsed.port else ""
    return urlunparse(parsed._replace(netloc="%s%s%s" % (auth, host, port)))


def envUpdates(env: Dict[str, str], host: str, network: str, valkeyPass: Optional[str],
               mainNode: str) -> Dict[str, str]:
    updates = {nodes.DEPLOYMENT_MODE_KEY: "multi-node", nodes.MAIN_NODE_KEY: mainNode, NETWORK_KEY: network}
    if (env.get("POSTGRES_HOST") or "localhost").strip() in LOOPBACK_HOSTS:
        updates["POSTGRES_HOST"] = host
        if env.get("DATABASE_URL"):
            updates["DATABASE_URL"] = withHost(env["DATABASE_URL"], host)
    for key in ("BROKER_URL", "RESULT_BACKEND_URL"):
        url = (env.get(key) or "").strip()
        if url and (urlparse(url).hostname or "") in LOOPBACK_HOSTS:
            updates[key] = withHost(url, host, valkeyPass)
    return updates


def isLocal(host: str) -> bool:
    host = (host or "localhost").strip()
    if host in LOOPBACK_HOSTS:
        return True
    try:
        target = socket.gethostbyname(host)
        local = {socket.gethostbyname(socket.gethostname()), "127.0.0.1", "127.0.1.1"}
        return target in local or target.startswith("127.")
    except OSError:
        return False


# The plan ---------------------------------------------------------------------------------------------------------

class Step:
    def __init__(self, title: str, action: Callable[[], None]):
        self.title, self.action = title, action


def _serviceName(runner: Runner, candidates: Tuple[str, ...]) -> Optional[str]:
    result = runner.run(["systemctl", "list-unit-files", "--type=service", "--no-legend"], check=False)
    names = {line.split()[0].rsplit(".", 1)[0] for line in result.stdout.splitlines() if line.split()}
    return next((name for name in candidates if name in names), None)


def _psql(runner: Runner, sql: str) -> str:
    """One statement as the database's administrator (as the installer sets the database up)."""
    return runner.run(["sudo", "-u", "postgres", "psql", "-d", "postgres", "-tAc", sql]).stdout.strip()


def _readRoot(runner: Runner, path: str) -> str:
    return runner.run(["cat", path], sudo=True).stdout


def _writeRoot(runner: Runner, path: str, content: str) -> None:
    runner.run(["tee", path], sudo=True, inputText=content)


def _backup(runner: Runner, source: str, backupDir: Path) -> None:
    backupDir.mkdir(parents=True, exist_ok=True)
    target = backupDir / Path(source).name
    runner.run(["cp", "-p", source, str(target)], sudo=True)
    runner.run(["chown", "%d:%d" % (os.getuid(), os.getgid()), str(target)], sudo=True, check=False)


def buildPlan(env: Dict[str, str], envPath: Path, scipionHome: Path, network: str, host: str,
              runner: Runner, restart: Callable[[], None]) -> Tuple[List[Step], List[str]]:
    """The steps to open this main node to the nodes' network, and the warnings to show before them."""
    warnings: List[str] = []
    steps: List[Step] = []
    backupDir = Path(scipionHome) / "multinode" / ("backup-%s" % time.strftime("%Y%m%d-%H%M%S"))
    state: Dict[str, Optional[str]] = {"valkeyPass": None}

    # PostgreSQL, when it runs here
    if isLocal(env.get("POSTGRES_HOST") or "localhost"):
        database, user = env.get("DATABASE_NAME") or "", env.get("DATABASE_USER") or ""

        def configurePostgres() -> None:
            hbaFile = _psql(runner, "SHOW hba_file")
            method = _psql(runner, "SHOW password_encryption") or "scram-sha-256"
            method = "md5" if method == "md5" else "scram-sha-256"
            content = _readRoot(runner, hbaFile)
            updated, changed = withHbaLine(content, hbaLine(database, user, network, method))
            if changed:
                _backup(runner, hbaFile, backupDir)
                _writeRoot(runner, hbaFile, updated)
            if _psql(runner, "SHOW listen_addresses") != "*":
                _psql(runner, "ALTER SYSTEM SET listen_addresses = '*'")
            service = _serviceName(runner, ("postgresql",)) or "postgresql"
            runner.run(["systemctl", "restart", service], sudo=True)

        steps.append(Step("PostgreSQL: listen on the network and let %s into %s from %s (pg_hba.conf), then "
                          "restart it" % (user, database, network), configurePostgres))
    else:
        warnings.append("The database is not on this machine (%s): open it to %s yourself."
                        % (env.get("POSTGRES_HOST"), network))

    # Valkey, when it runs here
    brokerUrl = (env.get("BROKER_URL") or "").strip()
    brokerHost = urlparse(brokerUrl).hostname or "localhost"
    if isLocal(brokerHost):
        def configureValkey() -> None:
            info = runner.run(["valkey-cli"] + _valkeyAuth(brokerUrl) + ["INFO", "server"]).stdout
            configFile = next((line.split(":", 1)[1].strip() for line in info.splitlines()
                               if line.startswith("config_file:")), "")
            if not configFile:
                raise RuntimeError("Valkey runs without a configuration file: give it one (valkey.conf) first")
            content = _readRoot(runner, configFile)
            password = valkeyPassword(content) or urlparse(brokerUrl).password or secrets.token_urlsafe(24)
            state["valkeyPass"] = password
            _backup(runner, configFile, backupDir)
            _writeRoot(runner, configFile, valkeyConfig(content, password))
            service = _serviceName(runner, ("valkey-server", "valkey", "redis-server")) or "valkey-server"
            runner.run(["systemctl", "restart", service], sudo=True)

        steps.append(Step("Valkey: listen on the network with a password (valkey.conf), then restart it. "
                          "Anything else on this machine using Valkey without a password stops reaching it.",
                          configureValkey))
    else:
        warnings.append("Valkey is not on this machine (%s): open it to %s yourself." % (brokerHost, network))

    # The firewall, when ufw guards this machine
    def configureFirewall() -> None:
        status = runner.run(["ufw", "status"], sudo=True, check=False)
        if "Status: active" not in (status.stdout or ""):
            return
        for port in ("5432", "6379"):
            runner.run(["ufw", "allow", "from", network, "to", "any", "port", port, "proto", "tcp"], sudo=True)

    steps.append(Step("Firewall: if ufw is active, let %s reach ports 5432 and 6379" % network, configureFirewall))

    def configureEnv() -> None:
        backupDir.mkdir(parents=True, exist_ok=True)
        (backupDir / ".env").write_text(envPath.read_text())
        os.chmod(backupDir / ".env", 0o600)
        writeEnvFile(envPath, envUpdates(readEnvFile(envPath), host, network, state["valkeyPass"],
                                         nodes.nodeName()))

    steps.append(Step(".env: name this machine as %s instead of localhost, multi-node" % host, configureEnv))
    steps.append(Step("Restart the API and the workers of this machine with the new settings", restart))
    return steps, warnings


def _valkeyAuth(brokerUrl: str) -> List[str]:
    password = urlparse(brokerUrl).password
    return ["--no-auth-warning", "-a", password] if password else []


def checkNetwork(network: str) -> str:
    """The network in CIDR form (10.0.0.0/24); ValueError when it is not one, or is every address."""
    parsed = ipaddress.ip_network(network.strip(), strict=False)
    if parsed.prefixlen == 0:
        raise ValueError("%s is every address: give the nodes' network, e.g. 10.0.0.0/24" % network)
    return str(parsed)


def defaultHost() -> str:
    return socket.getfqdn() or socket.gethostname()
