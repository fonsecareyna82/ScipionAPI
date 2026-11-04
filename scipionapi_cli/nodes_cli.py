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
"""`scipionapi multinode enable` (on the main node) and `scipionapi node join|leave|list` (on a compute node)."""
from typing import Optional

import typer

from scipionapi_cli import multinode, nodes, runtime
from scipionapi_cli.shell import resolveRepoRoot

multinodeApp = typer.Typer(help="Open the main node to compute nodes.", no_args_is_help=True)
nodeApp = typer.Typer(help="Make this machine a compute node of the installation, or stop being one.",
                      no_args_is_help=True)

console = runtime.console


def _context():
    repoRoot = resolveRepoRoot()
    env = runtime._loadEnv(repoRoot)
    return repoRoot, runtime._resolveScipionHome(repoRoot), runtime._resolveEnvPath(repoRoot), env


def _printCheck(check: nodes.Check) -> None:
    mark = "[green]OK[/green]    " if check.ok else ("[red]FAIL[/red]  " if check.required else "[yellow]WARN[/yellow]  ")
    console.print("%s %-28s %s" % (mark, check.label, check.detail))


@multinodeApp.command("enable", help=(
        "Let compute nodes reach this main node: PostgreSQL and Valkey listen on the network (Valkey with a "
        "password), only the nodes' network gets in, the firewall (ufw) lets it, and the .env names this machine "
        "instead of localhost. Every file changed is backed up first under scipion_home/multinode/."))
def enable(
        network: str = typer.Option(..., "--network", help="The nodes' network, e.g. 10.0.0.0/24."),
        host: Optional[str] = typer.Option(None, "--host",
                                           help="This machine's name as the nodes reach it (default: its FQDN)."),
        dryRun: bool = typer.Option(False, "--dry-run", help="Show what would change, and change nothing."),
        yes: bool = typer.Option(False, "--yes", "-y", help="Do not ask for confirmation."),
) -> None:
    repoRoot, scipionHome, envPath, env = _context()
    if nodes.readProfile(scipionHome):
        raise typer.BadParameter("This machine is a compute node (%s): run it on the main node"
                                 % nodes.profilePath(scipionHome))
    try:
        network = multinode.checkNetwork(network)
    except ValueError as error:
        raise typer.BadParameter(str(error), param_hint="--network")
    host = (host or multinode.defaultHost()).strip()
    if host in multinode.LOOPBACK_HOSTS:
        raise typer.BadParameter("%s cannot be reached from the nodes: give this machine's network name" % host,
                                 param_hint="--host")

    steps, warnings = multinode.buildPlan(env, envPath, scipionHome, network, host, multinode.Runner(),
                                          restart=lambda: runtime.restartCommand("all"))
    console.print("[bold]Opening this main node (%s) to the nodes of %s[/bold]" % (host, network))
    for number, step in enumerate(steps, start=1):
        console.print("  %d. %s" % (number, step.title))
    for warning in warnings:
        console.print("[yellow]WARN[/yellow]  %s" % warning)
    if dryRun:
        console.print("Dry run: nothing changed.")
        return
    if not yes and not typer.confirm("Go ahead?", default=False):
        raise typer.Exit(1)

    for number, step in enumerate(steps, start=1):
        console.print("[cyan]%d.[/cyan] %s" % (number, step.title))
        step.action()

    env = runtime._loadEnv(repoRoot)
    for label, (ok, detail) in (("Database", nodes.checkDatabase(env)), ("Valkey", nodes.checkBroker(env))):
        _printCheck(nodes.Check("%s by %s" % (label, host), ok, detail))
    console.print("\n[bold]Next, on each compute node[/bold] (same user, this installation mounted at the same path):")
    console.print("  %s/scripts/scipionapi node join --queue protocols" % repoRoot)
    console.print("  (GPU nodes with their own queue: node join --queue protocols-gpu --host gpu-nodes)")


@nodeApp.command("join", help=(
        "Make this machine a compute node: check it sees the installation, the projects, the database and Valkey "
        "like the main node, save its profile (scipion_home/nodes/<node>.env) and start its protocol worker."))
def join(
        queue: Optional[str] = typer.Option(None, "--queue",
                                            help="The Celery queue this node takes protocols from (default: protocols)."),
        concurrency: Optional[int] = typer.Option(None, "--concurrency", min=1,
                                                  help="Protocols at a time (default: its GPUs, or 4)."),
        host: Optional[str] = typer.Option(None, "--host", help=(
                "A Scipion host (as users pick in a protocol's form) whose protocols go to this node's queue; "
                "made as a copy of localhost when it does not exist, e.g. --queue protocols-gpu --host gpu-nodes.")),
) -> None:
    repoRoot, scipionHome, envPath, env = _context()
    if host and not queue:
        raise typer.BadParameter("give the node its own --queue for that host's protocols", param_hint="--host")
    console.print("[bold]Checking this machine (%s) as a compute node[/bold]" % nodes.nodeName())
    joined = nodes.joinNode(repoRoot, scipionHome, env, queue, concurrency, _printCheck,
                            start=lambda: runtime.startCommand("protocols"), scipionHost=host)
    if not joined:
        console.print("[red]This machine cannot be a node yet: fix what failed and run it again.[/red]")
        raise typer.Exit(1)
    name = nodes.nodeName()
    if nodes.waitForWorker(name):
        console.print("[green]The worker of %s answers: it takes protocols from now on.[/green]" % name)
    else:
        console.print("[yellow]The worker started, but it did not answer yet: see 'scipionapi logs' on this "
                      "node.[/yellow]")
    console.print("Profile: %s" % nodes.profilePath(scipionHome))
    if host:
        console.print("Protocols whose host is [bold]%s[/bold] now run on the queue %s (choose it in the "
                      "protocol's form)." % (host, queue))


@nodeApp.command("leave", help="Stop this node's protocol worker and forget its profile.")
def leave() -> None:
    repoRoot, scipionHome, envPath, env = _context()
    if not nodes.leaveNode(scipionHome, stop=lambda: runtime.stopCommand("protocols")):
        console.print("This machine is not a compute node.")
        raise typer.Exit(1)
    console.print("%s is no longer a compute node." % nodes.nodeName())


@nodeApp.command("list", help="The compute nodes of the installation and the workers answering now.")
def listNodes() -> None:
    repoRoot, scipionHome, envPath, env = _context()
    workers = nodes.liveWorkers()
    console.print("Main node: %s" % (env.get(nodes.MAIN_NODE_KEY) or "(single-node installation)"))
    profiles = nodes.listProfiles(scipionHome)
    if not profiles:
        console.print("No compute nodes yet.")
    for name, profile in profiles:
        live = [worker for worker in workers if worker.split("@", 1)[-1].split(".", 1)[0].lower() == name]
        console.print("  %-20s queue %-18s concurrency %-3s %s" % (
            name, profile.get("PROTOCOLS_CELERY_QUEUE") or nodes.DEFAULT_QUEUE,
            profile.get("PROTOCOL_WORKER_CONCURRENCY") or "-",
            "[green]answering[/green]" if live else "[yellow]not answering[/yellow]"))
    others = [worker for worker in workers
              if worker.split("@", 1)[-1].split(".", 1)[0].lower() not in {name for name, _ in profiles}]
    for worker in sorted(others):
        console.print("  %-20s %s" % (worker, ", ".join(workers[worker])))
