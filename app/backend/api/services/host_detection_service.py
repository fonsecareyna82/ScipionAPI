"""
Setting up the host from what this server has: which scheduler it can send jobs to, its queues (partitions) and their
limits, as a proposal for Settings → Host; and a small test job sent with a host configuration, to see it works
before a protocol needs it.

Nothing here is saved: the proposal goes to the form, and the admin saves it.
"""
import json
import logging
import re
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

Runner = Callable[[List[str]], str]

# The order matters: qsub belongs to several schedulers, told apart by their other commands
SCHEDULER_COMMANDS = [
    ("slurm", "SLURM", ["sbatch", "squeue", "sinfo"]),
    ("lsf", "LSF", ["bsub", "bjobs"]),
    ("sge", "SGE", ["qsub", "qconf"]),
    ("pbs", "PBS/TORQUE", ["qsub", "pbsnodes"]),
    ("condor", "HTCondor", ["condor_submit"]),
]

SUPPORTED = {"slurm", "pbs", "sge"}

DEFAULT_MEMORY_MB = 8192
DEFAULT_HOURS = 24

SLURM_TEMPLATE = """#!/bin/bash
# Inherit all current environment variables
#SBATCH --export=ALL
# Job name
#SBATCH -J %_(JOB_NAME)s
# Outputs
#SBATCH -o %_(JOB_SCRIPT)s.out
#SBATCH -e %_(JOB_SCRIPT)s.err
#SBATCH --open-mode=append
# Partition (queue) name
#SBATCH -p %_(JOB_QUEUE)s
# Time, number of tasks, cores per task and memory (MB) for the job
#SBATCH --time=%_(JOB_TIME)s:00:00 --ntasks=%_(JOB_NODES)d --cpus-per-task=%_(JOB_THREADS)d --mem=%_(JOB_MEMORY)s{gres}

%_(JOB_COMMAND)s"""


def _run(command: List[str]) -> str:
    completed = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=20)
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout or "").strip() or f"{command[0]} failed")
    return completed.stdout


def detectScheduler(which: Optional[Callable[[str], Optional[str]]] = None) -> Optional[Dict[str, str]]:
    """The scheduler whose commands this server has, or None."""
    which = which or shutil.which
    for key, name, commands in SCHEDULER_COMMANDS:
        if all(which(command) for command in commands):
            return {"key": key, "name": name}
    return None


def _slurmHours(limit: str) -> Optional[int]:
    """A partition's time limit in whole hours (None: no limit). Slurm writes [days-]hours[:minutes[:seconds]]."""
    limit = (limit or "").strip().lower()
    if not limit or limit in ("infinite", "unlimited", "n/a"):
        return None
    days = 0
    if "-" in limit:
        dayText, limit = limit.split("-", 1)
        days = int(dayText or 0)
    parts = [int(part or 0) for part in limit.split(":")]
    # minutes alone, minutes:seconds, or hours:minutes:seconds
    if len(parts) == 1:
        hours = parts[0] / 60
    elif len(parts) == 2:
        hours = parts[0] / 60
    else:
        hours = parts[0] + parts[1] / 60
    return max(1, int(days * 24 + hours))


def _slurmGpus(gres: str) -> int:
    """GPUs per node from Slurm's GRES text, e.g. gpu:4, gpu:a100:4(S:0-1), gpu:2,shard:8."""
    total = 0
    for item in (gres or "").split(","):
        item = re.sub(r"\(.*?\)", "", item.strip())
        if not item.startswith("gpu"):
            continue
        last = item.split(":")[-1]
        if last.isdigit():
            total = max(total, int(last))
    return total


def slurmPartitions(run: Runner = _run) -> List[Dict[str, Any]]:
    """Each partition of the cluster with what its nodes have: the default one first.

    On a cluster that starts its machines only when a job comes (in the cloud), the machines that are off may not be
    listed, so what they have is read from the scheduler's configuration instead."""
    output = run(["sinfo", "-h", "-o", "%P|%l|%c|%m|%G|%a|%D|%T"])
    partitions: Dict[str, Dict[str, Any]] = {}
    digits = lambda text: int(re.sub(r"\D", "", text) or 0)  # noqa: E731 - e.g. "12+" or "31788+"
    for line in output.splitlines():
        fields = line.strip().split("|")
        if len(fields) < 7 or not fields[0]:
            continue
        rawName, limit, cpus, memory, gres, available, nodes = fields[:7]
        state = fields[7].strip() if len(fields) > 7 else ""
        name = rawName.rstrip("*")
        entry = partitions.setdefault(name, _newPartition(name, rawName.endswith("*"), _slurmHours(limit)))
        entry["cpus"] = max(entry["cpus"], digits(cpus))
        entry["memoryMb"] = max(entry["memoryMb"], digits(memory))
        entry["gpus"] = max(entry["gpus"], _slurmGpus(gres))
        entry["nodes"] += digits(nodes)
        entry["up"] = entry["up"] or available.strip().lower() == "up"
        # Slurm marks a machine that is off (powered down) with "~"
        entry["asleep"] = entry["asleep"] or state.endswith("~")

    if not partitions or any(not entry["cpus"] or not entry["memoryMb"] for entry in partitions.values()):
        _fillFromConfiguration(partitions, run)
    for entry in partitions.values():
        entry["unknown"] = not entry["cpus"]
    return sorted(partitions.values(), key=lambda partition: (not partition["default"], partition["name"]))


def _newPartition(name: str, default: bool, hours: Optional[int]) -> Dict[str, Any]:
    return {"name": name, "default": default, "hours": hours, "cpus": 0, "memoryMb": 0, "gpus": 0, "nodes": 0,
            "up": False, "asleep": False, "unknown": False}


def _scontrol(run: Runner, what: str) -> List[Dict[str, str]]:
    """Each record of `scontrol show <what>` as its key=value pairs ([] when it cannot be read)."""
    try:
        output = run(["scontrol", "-a", "-o", "show", what])
    except Exception:
        return []
    return [dict(re.findall(r"(\w+)=(\S*)", line)) for line in output.splitlines() if "=" in line]


def _number(text: Optional[str]) -> int:
    return int(text) if (text or "").isdigit() else 0


def _fillFromConfiguration(partitions: Dict[str, Dict[str, Any]], run: Runner) -> None:
    """Complete the partitions with what the configuration says their machines have, also when they are off."""
    for record in _scontrol(run, "partition"):
        name = record.get("PartitionName")
        if not name or record.get("Hidden") == "YES":
            continue
        entry = partitions.setdefault(name, _newPartition(name, record.get("Default") == "YES",
                                                          _slurmHours(record.get("MaxTime", ""))))
        entry["up"] = entry["up"] or record.get("State") == "UP"

    configured: Dict[str, Dict[str, Any]] = {}
    for record in _scontrol(run, "node"):
        state = record.get("State", "").upper()
        for name in filter(None, record.get("Partitions", "").split(",")):
            seen = configured.setdefault(name, {"cpus": 0, "memoryMb": 0, "gpus": 0, "nodes": 0, "asleep": False})
            seen["cpus"] = max(seen["cpus"], _number(record.get("CPUTot")))
            seen["memoryMb"] = max(seen["memoryMb"], _number(record.get("RealMemory")))
            seen["gpus"] = max(seen["gpus"], _slurmGpus(record.get("Gres", "")))
            seen["nodes"] += 1
            seen["asleep"] = seen["asleep"] or "POWERED_DOWN" in state or "POWER_DOWN" in state
    for name, seen in configured.items():
        entry = partitions.get(name)
        if entry is None:
            continue
        for key in ("cpus", "memoryMb", "gpus", "nodes"):
            entry[key] = max(entry[key], seen[key])
        entry["asleep"] = entry["asleep"] or seen["asleep"]


def slurmHostSettings(hostAlias: str, partitions: List[Dict[str, Any]]) -> Dict[str, Any]:
    """A host configuration for Slurm with one queue per partition, its values within the partition's limits."""
    withGpus = any(partition["gpus"] for partition in partitions)
    queues = []
    for partition in partitions:
        memory = min(DEFAULT_MEMORY_MB, partition["memoryMb"]) if partition["memoryMb"] else DEFAULT_MEMORY_MB
        hours = min(DEFAULT_HOURS, partition["hours"]) if partition["hours"] else DEFAULT_HOURS
        params = [
            {"variableName": "JOB_MEMORY", "value": str(memory), "label": "Memory (MB)",
             "help": f"Memory for this job, in megabytes"
                     + (f" (at most {partition['memoryMb']} on this queue)" if partition["memoryMb"] else "")},
            {"variableName": "JOB_TIME", "value": str(hours), "label": "Time (hours)",
             "help": "The longest this job may run, in hours"
                     + (f" (at most {partition['hours']} on this queue)" if partition["hours"] else "")},
        ]
        if withGpus:
            params.append({"variableName": "GPU_COUNT", "value": str(min(1, partition["gpus"])),
                           "label": "Number of GPUs",
                           "help": f"GPUs for this job (this queue's machines have {partition['gpus']})"})
        params.append({"variableName": "QUEUE_FOR_JOBS", "value": "N", "label": "Use queue for jobs",
                       "help": "Send each step of the protocol as its own job"})
        queues.append({"name": partition["name"], "params": params})

    return {
        "hostAlias": hostAlias or "localhost",
        "schedulerName": "SLURM",
        "mandatory": False,
        "parallelCommand": "mpirun -np %_(JOB_NODES)d %_(COMMAND)s",
        "submitCommand": "sbatch --parsable %_(JOB_SCRIPT)s",
        "cancelCommand": "scancel %_(JOB_ID)s",
        "checkCommand": "squeue -h -j %_(JOB_ID)s",
        "jobDoneRegex": "",
        "submitTemplate": SLURM_TEMPLATE.replace("{gres}", " --gres=gpu:%_(GPU_COUNT)s" if withGpus else ""),
        "queues": queues,
    }


PBS_TEMPLATE = """#!/bin/bash
# Inherit all current environment variables
#PBS -V
# Job name
#PBS -N %_(JOB_NAME)s
# Queue name
#PBS -q %_(JOB_QUEUE)s
# Outputs
#PBS -o %_(JOB_SCRIPT)s.out
#PBS -e %_(JOB_SCRIPT)s.err
# Machines and cores, time and memory (MB) for the job
#PBS -l nodes=%_(JOB_NODES)d:ppn=%_(JOB_THREADS)d
#PBS -l walltime=%_(JOB_TIME)s:00:00
#PBS -l mem=%_(JOB_MEMORY)smb
cd $PBS_O_WORKDIR

%_(JOB_COMMAND)s"""

SGE_TEMPLATE = """#!/bin/bash
# Inherit all current environment variables
#$ -V
# Job name
#$ -N %_(JOB_NAME)s
# Outputs
#$ -o %_(JOB_SCRIPT)s.out
#$ -e %_(JOB_SCRIPT)s.err
# Queue name
#$ -q %_(JOB_QUEUE)s
# Time and memory (MB, per core) for the job{pe}
#$ -l h_rt=%_(JOB_TIME)s:00:00
#$ -l h_vmem=%_(JOB_MEMORY)sM
#$ -cwd

%_(JOB_COMMAND)s"""


def _hoursOfClock(text: str) -> Optional[int]:
    """[days:]hours:minutes:seconds (or seconds alone) as whole hours; None: no limit."""
    text = (text or "").strip().lower()
    if not text or text in ("infinity", "unlimited"):
        return None
    try:
        parts = [int(float(part or 0)) for part in text.split(":")]
    except ValueError:
        return None
    if len(parts) == 1:
        seconds = parts[0]
    else:
        while len(parts) < 4:
            parts.insert(0, 0)
        days, hours, minutes, secs = parts[-4:]
        seconds = ((days * 24 + hours) * 60 + minutes) * 60 + secs
    return max(1, seconds // 3600) if seconds else None


def _megabytes(text: str) -> int:
    """A memory size as PBS or SGE write it (64gb, 16G, 4000mb, 1048576kb, a number of bytes) in MB."""
    found = re.match(r"^\s*([\d.]+)\s*([kmgtp]?)(i?b?)?\s*$", (text or "").strip(), re.IGNORECASE)
    if not found:
        return 0
    value = float(found.group(1))
    unit = found.group(2).lower()
    factor = {"": 1 / (1024 * 1024), "k": 1 / 1024, "m": 1, "g": 1024, "t": 1024 ** 2, "p": 1024 ** 3}[unit]
    return int(value * factor)


def pbsQueues(run: Runner = _run) -> List[Dict[str, Any]]:
    """The execution queues of a PBS/Torque server with their limits, the default one first."""
    default = ""
    try:
        found = re.search(r"default_queue\s*=\s*(\S+)", run(["qstat", "-B", "-f"]))
        default = found.group(1) if found else ""
    except Exception:  # noqa: BLE001 - without it, no queue is marked as the default
        pass
    queues: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    attributes: Dict[str, str] = {}

    def close():
        if current is None:
            return
        if attributes.get("queue_type", "execution").lower().startswith("e"):
            current.update(
                hours=_hoursOfClock(attributes.get("resources_max.walltime", "")),
                memoryMb=_megabytes(attributes.get("resources_max.mem", "")),
                cpus=int(re.sub(r"\D", "", attributes.get("resources_max.ncpus", "")) or 0),
                gpus=int(re.sub(r"\D", "", attributes.get("resources_max.ngpus", "")) or 0),
                up=attributes.get("enabled", "true").lower() == "true"
                   and attributes.get("started", "true").lower() == "true",
            )
            queues.append(current)

    for line in run(["qstat", "-Q", "-f"]).splitlines():
        if line.startswith("Queue:"):
            close()
            name = line.split(":", 1)[1].strip()
            current = {"name": name, "default": name == default, "hours": None, "cpus": 0, "memoryMb": 0, "gpus": 0,
                       "nodes": 0, "up": True}
            attributes = {}
        elif "=" in line and current is not None:
            key, _, value = line.strip().partition("=")
            attributes[key.strip().lower()] = value.strip()
    close()
    return sorted(queues, key=lambda queue: (not queue["default"], queue["name"]))


def sgeQueues(run: Runner = _run) -> List[Dict[str, Any]]:
    """The cluster queues of a Grid Engine with their limits."""
    queues = []
    for name in [line.strip() for line in run(["qconf", "-sql"]).splitlines() if line.strip()]:
        attributes: Dict[str, str] = {}
        for line in run(["qconf", "-sq", name]).splitlines():
            parts = line.split(None, 1)
            if len(parts) == 2:
                attributes[parts[0].lower()] = parts[1].strip()
        # slots is "8" or "1,[n1=16],[n2=16]": the most a machine of the queue gives
        slots = [int(number) for number in re.findall(r"(?:^|[=,])\s*(\d+)", attributes.get("slots", ""))]
        # Host groups (@name) are not counted: only the machines named
        hosts = [host for host in attributes.get("hostlist", "").split()
                 if host.upper() != "NONE" and not host.startswith("@")]
        queues.append({
            "name": name, "default": False, "hours": _hoursOfClock(attributes.get("h_rt", "")),
            "cpus": max(slots) if slots else 0, "memoryMb": _megabytes(attributes.get("h_vmem", "")),
            "gpus": 0, "nodes": len(hosts), "up": True,
        })
    return queues


def sgeThreadsEnvironment(run: Runner = _run) -> str:
    """The parallel environment that gives a job several cores of one machine, if the cluster has one."""
    try:
        names = [line.strip() for line in run(["qconf", "-spl"]).splitlines() if line.strip()]
    except Exception:  # noqa: BLE001 - jobs then ask for one core
        return ""
    for wanted in ("smp", "shm", "threads", "openmp", "make"):
        for name in names:
            if name.lower() == wanted:
                return name
    for name in names:
        if any(word in name.lower() for word in ("smp", "shm", "thread")):
            return name
    return ""


def _queueParams(queue: Dict[str, Any], withGpus: bool, memoryLabel: str = "Memory (MB)") -> List[Dict[str, str]]:
    memory = min(DEFAULT_MEMORY_MB, queue["memoryMb"]) if queue["memoryMb"] else DEFAULT_MEMORY_MB
    hours = min(DEFAULT_HOURS, queue["hours"]) if queue["hours"] else DEFAULT_HOURS
    params = [
        {"variableName": "JOB_MEMORY", "value": str(memory), "label": memoryLabel,
         "help": "Memory for this job, in megabytes"
                 + (f" (at most {queue['memoryMb']} on this queue)" if queue["memoryMb"] else "")},
        {"variableName": "JOB_TIME", "value": str(hours), "label": "Time (hours)",
         "help": "The longest this job may run, in hours"
                 + (f" (at most {queue['hours']} on this queue)" if queue["hours"] else "")},
    ]
    if withGpus:
        params.append({"variableName": "GPU_COUNT", "value": str(min(1, queue["gpus"])), "label": "Number of GPUs",
                       "help": f"GPUs for this job (this queue's machines have {queue['gpus']})"})
    params.append({"variableName": "QUEUE_FOR_JOBS", "value": "N", "label": "Use queue for jobs",
                   "help": "Send each step of the protocol as its own job"})
    return params


def pbsHostSettings(hostAlias: str, queues: List[Dict[str, Any]]) -> Dict[str, Any]:
    """A host configuration for PBS/Torque with its execution queues."""
    return {
        "hostAlias": hostAlias or "localhost",
        "schedulerName": "PBS/TORQUE",
        "mandatory": False,
        "parallelCommand": "mpirun -np %_(JOB_NODES)d %_(COMMAND)s",
        "submitCommand": "qsub %_(JOB_SCRIPT)s",
        "cancelCommand": "qdel %_(JOB_ID)s",
        "checkCommand": "qstat -f %_(JOB_ID)s 2>/dev/null | grep job_state",
        "jobDoneRegex": "job_state = [CF]",
        "submitTemplate": PBS_TEMPLATE,
        "queues": [{"name": queue["name"], "params": _queueParams(queue, False)} for queue in queues],
    }


def sgeHostSettings(hostAlias: str, queues: List[Dict[str, Any]], threadsEnvironment: str) -> Dict[str, Any]:
    """A host configuration for Grid Engine with its queues; several cores through its parallel environment."""
    pe = f"\n#$ -pe {threadsEnvironment} %_(JOB_THREADS)d" if threadsEnvironment else ""
    return {
        "hostAlias": hostAlias or "localhost",
        "schedulerName": "SGE",
        "mandatory": False,
        "parallelCommand": "mpirun -np %_(JOB_NODES)d %_(COMMAND)s",
        "submitCommand": "qsub %_(JOB_SCRIPT)s",
        "cancelCommand": "qdel %_(JOB_ID)s",
        "checkCommand": "qstat -j %_(JOB_ID)s 2>&1",
        "jobDoneRegex": "do not exist",
        "submitTemplate": SGE_TEMPLATE.replace("{pe}", pe),
        "queues": [{"name": queue["name"], "params": _queueParams(queue, False, "Memory per core (MB)")}
                   for queue in queues],
    }


def _readAndBuild(key: str, hostAlias: str, run: Runner):
    if key == "slurm":
        queues = slurmPartitions(run)
        return queues, (slurmHostSettings(hostAlias, queues) if queues else None)
    if key == "pbs":
        queues = pbsQueues(run)
        return queues, (pbsHostSettings(hostAlias, queues) if queues else None)
    queues = sgeQueues(run)
    return queues, (sgeHostSettings(hostAlias, queues, sgeThreadsEnvironment(run)) if queues else None)


def detectHost(hostAlias: str, which: Optional[Callable[[str], Optional[str]]] = None,
               run: Runner = _run) -> Dict[str, Any]:
    """What this server can send jobs to, and the host configuration proposed for it."""
    scheduler = detectScheduler(which)
    if scheduler is None:
        return {"scheduler": None, "supported": False, "settings": None, "queues": [],
                "message": "No scheduler found on this server: protocols run directly on it, no queues needed."}
    if scheduler["key"] not in SUPPORTED:
        return {"scheduler": scheduler["name"], "supported": False, "settings": None, "queues": [],
                "message": f"{scheduler['name']} found. It cannot be set up automatically yet: fill in the form "
                           "by hand."}
    try:
        queues, settings = _readAndBuild(scheduler["key"], hostAlias, run)
    except Exception as exc:  # noqa: BLE001 - the scheduler's own message is what helps
        return {"scheduler": scheduler["name"], "supported": True, "settings": None, "queues": [],
                "message": f"{scheduler['name']} found, but its queues could not be read: {exc}"}
    if not queues:
        return {"scheduler": scheduler["name"], "supported": True, "settings": None, "queues": [],
                "message": f"{scheduler['name']} found, but it has no queues."}
    message = f"{scheduler['name']} found with {len(queues)} {'queue' if len(queues) == 1 else 'queues'}."
    if any(queue.get("asleep") for queue in queues):
        message += " Its machines start when a job comes, so the first job of a queue waits for one to start."
    if any(queue.get("unknown") for queue in queues):
        message += " What some machines have is not known while they are off: check memory and GPUs by hand."
    return {
        "scheduler": scheduler["name"],
        "supported": True,
        "settings": settings,
        "queues": queues,
        "message": message + " Check the proposal, then save it.",
    }


# A test job --------------------------------------------------------------------------------------------------------

TEST_COMMAND = 'echo "ScipionWeb test job ran on $(hostname) at $(date)"'
TEST_TIMEOUT_SECONDS = 15 * 60
POLL_SECONDS = 3

_tests: Dict[str, Dict[str, Any]] = {}
_testsLock = threading.Lock()


def _queueValues(settings: Dict[str, Any], queueName: str) -> Dict[str, str]:
    for queue in settings.get("queues") or []:
        if queue.get("name") == queueName:
            return {str(param.get("variableName")): str(param.get("value") or "") for param in queue.get("params") or []
                    if param.get("variableName")}
    return {}


def _format(text: str, values: Dict[str, Any]) -> str:
    """As Scipion does: %_(NAME)s are the job's values."""
    try:
        return text.replace("%_(", "%(") % values
    except KeyError as exc:
        raise ValueError(f"It uses %_({exc.args[0]})s, which neither the job nor the queue gives a value.") from None
    except (TypeError, ValueError) as exc:
        raise ValueError(f"It could not be filled in: {exc}") from None


def buildTestJob(settings: Dict[str, Any], queueName: str, folder: Path) -> Dict[str, Any]:
    """The script and the commands of a test job, filled in as for a protocol."""
    script = folder / "scipionweb_test_job.sh"
    values: Dict[str, Any] = {
        "JOB_NAME": "scipionweb-test", "JOB_SCRIPT": str(script), "JOB_COMMAND": TEST_COMMAND, "COMMAND": TEST_COMMAND,
        "JOB_QUEUE": queueName, "JOB_NODES": 1, "JOB_THREADS": 1, "JOB_CORES": 1, "JOB_HOURS": 1,
        "JOB_NODEFILE": str(folder / "nodefile"), "JOB_ID": "", "GPU_COUNT": 0,
    }
    values.update(_queueValues(settings, queueName))
    return {
        "script": script,
        "scriptText": _format(settings.get("submitTemplate") or "", values),
        "submit": _format(settings.get("submitCommand") or "", values),
        "values": values,
    }


def _setTest(testId: str, **changes):
    with _testsLock:
        _tests[testId].update(changes, updatedAt=time.time())


def _jobOutput(script: Path) -> str:
    parts = []
    for suffix in (".out", ".err"):
        path = Path(str(script) + suffix)
        if path.exists():
            text = path.read_text(errors="replace").strip()
            if text:
                parts.append(text[-4000:])
    return "\n".join(parts)


def _shell(command: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(command, shell=True, cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          text=True, timeout=60)


def _runTest(testId: str, settings: Dict[str, Any], queueName: str, folder: Path):
    try:
        folder.mkdir(parents=True, exist_ok=True)
        job = buildTestJob(settings, queueName, folder)
        job["script"].write_text(job["scriptText"] + "\n\n")
        _setTest(testId, state="submitting", script=job["scriptText"], submitCommand=job["submit"])

        submitted = _shell(job["submit"], folder)
        found = re.search(r"(\d+)", (submitted.stdout or "").splitlines()[0] if submitted.stdout else "")
        if submitted.returncode != 0 or not found:
            _setTest(testId, state="failed", message="The job could not be sent to the queue.",
                     output=((submitted.stdout or "") + (submitted.stderr or "")).strip())
            return
        jobId = found.group(1)
        _setTest(testId, state="queued", jobId=jobId, message=f"Sent as job {jobId}, waiting for the queue.")

        check = _format(settings.get("checkCommand") or "", {"JOB_ID": jobId})
        doneRegex = settings.get("jobDoneRegex") or ""
        deadline = time.time() + TEST_TIMEOUT_SECONDS
        while time.time() < deadline:
            with _testsLock:
                if _tests[testId]["state"] == "cancelled":
                    return
            answer = _shell(check, folder)
            text = (answer.stdout or "").strip()
            done = not text or (doneRegex and re.search(doneRegex, text))
            if done:
                output = _jobOutput(job["script"])
                ran = "ScipionWeb test job ran on" in output
                _setTest(testId, state="finished" if ran else "failed", output=output,
                         message="The test job ran." if ran
                         else "The job left the queue without running the test command: see its output.")
                return
            _setTest(testId, state="running" if job["script"].with_suffix(".sh.out").exists() else "queued",
                     queueAnswer=text[-1000:])
            time.sleep(POLL_SECONDS)

        _setTest(testId, state="failed", message="No answer after 15 minutes: the job may still be waiting in the queue.")
    except ValueError as exc:
        _setTest(testId, state="failed", message=str(exc))
    except Exception as exc:  # noqa: BLE001 - shown to the admin as it is
        logger.exception("Host test job %s failed", testId)
        _setTest(testId, state="failed", message=str(exc))


def startTest(settings: Dict[str, Any], queueName: str, testsRoot: Path) -> Dict[str, Any]:
    """Sends a test job in the background; its progress is read with getTest."""
    if not (settings.get("queues") or []) or not queueName:
        raise ValueError("Choose a queue to send the test job to.")
    if not any(queue.get("name") == queueName for queue in settings["queues"]):
        raise ValueError(f"There is no queue {queueName}.")
    # Filled in now, so a mistake in the script or the command is told at once
    buildTestJob(settings, queueName, testsRoot / "check")
    testId = uuid.uuid4().hex[:12]
    with _testsLock:
        _tests[testId] = {"id": testId, "queue": queueName, "state": "starting", "message": "Preparing the job.",
                          "jobId": None, "output": "", "startedAt": time.time(), "updatedAt": time.time(),
                          "cancelCommand": settings.get("cancelCommand") or ""}
    threading.Thread(target=_runTest, args=(testId, json.loads(json.dumps(settings)), queueName,
                                            testsRoot / testId), daemon=True).start()
    return getTest(testId)


def getTest(testId: str) -> Dict[str, Any]:
    with _testsLock:
        test = _tests.get(testId)
        if test is None:
            raise KeyError(testId)
        return {key: value for key, value in test.items() if key != "cancelCommand"}


def cancelTest(testId: str) -> Dict[str, Any]:
    with _testsLock:
        test = _tests.get(testId)
        if test is None:
            raise KeyError(testId)
        jobId, cancel = test.get("jobId"), test.get("cancelCommand")
        test.update(state="cancelled", message="Cancelled.", updatedAt=time.time())
    if jobId and cancel:
        try:
            subprocess.run(_format(cancel, {"JOB_ID": jobId}), shell=True, timeout=30, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE)
        except Exception:  # noqa: BLE001 - the job ends by itself anyway
            logger.warning("Could not cancel the host test job %s", jobId)
    return getTest(testId)


# hosts.conf, for the installer and the doctor --------------------------------------------------------------------------

def _readHostsConf(path: Path):
    from configparser import RawConfigParser

    # As Scipion reads it: only ";" starts a comment, so the "#SBATCH" lines stay in the job script
    parser = RawConfigParser(comment_prefixes=";", strict=False)
    parser.optionxform = str  # keep the keys' case: Scipion reads them as written
    if path.exists():
        parser.read(path, encoding="utf-8")
    return parser


def configuredQueues(path: Path, section: str = "localhost") -> Optional[List[str]]:
    """The queues hosts.conf offers; None when it has none set up (missing, empty, or the installer's placeholder,
    a queue "default" with no values)."""
    parser = _readHostsConf(path)
    if not parser.has_section(section):
        return None
    try:
        queues = json.loads(parser.get(section, "QUEUES", fallback="") or "{}")
    except ValueError:
        return None
    if not isinstance(queues, dict) or not queues:
        return None
    if list(queues) == ["default"] and not queues["default"]:
        return None
    return list(queues)


def writeHostsConf(path: Path, settings: Dict[str, Any], section: str = "localhost") -> None:
    """Writes the host configuration into hosts.conf (keeping its other hosts and keys), as Settings → Host does."""
    parser = _readHostsConf(path)
    if not parser.has_section(section):
        parser.add_section(section)
    queues = {queue["name"]: [[param["variableName"], param.get("value", ""), param.get("label", ""),
                               param.get("help", "")] for param in queue.get("params") or []]
              for queue in settings.get("queues") or []}
    values = {
        "PARALLEL_COMMAND": settings.get("parallelCommand", ""),
        "NAME": settings.get("schedulerName", ""),
        "MANDATORY": "True" if settings.get("mandatory") else "False",
        "SUBMIT_COMMAND": settings.get("submitCommand", ""),
        "SUBMIT_TEMPLATE": settings.get("submitTemplate", ""),
        "CANCEL_COMMAND": settings.get("cancelCommand", ""),
        "CHECK_COMMAND": settings.get("checkCommand", ""),
        "JOB_DONE_REGEX": json.dumps(settings.get("jobDoneRegex", "")),
        "QUEUES": json.dumps(queues, indent=4),
    }
    for key, value in values.items():
        parser.set(section, key, value)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        parser.write(handle)


def autoConfigureHostsConf(path: Path, which: Optional[Callable[[str], Optional[str]]] = None,
                           run: Runner = _run) -> Dict[str, Any]:
    """For the installer: when hosts.conf has no queues set up and this server has a scheduler, writes its
    configuration (the old file is kept beside it). Returns what was found and whether it was written."""
    if configuredQueues(path) is not None:
        return {"written": False, "reason": "configured", "message": "Already set up: left as it is."}
    found = detectHost("localhost", which, run)
    if not found["settings"]:
        return {"written": False, "reason": "nothing", "message": found["message"], "detection": found}
    if path.exists():
        shutil.copy2(path, str(path) + ".before-detect")
    writeHostsConf(path, found["settings"])
    names = ", ".join(queue["name"] for queue in found["queues"])
    return {"written": True, "reason": "written", "detection": found,
            "message": f"{found['scheduler']} with the queues {names}. Check it, and send a test job, in "
                       "Settings → Host."}


def checkHostsConf(path: Path, which: Optional[Callable[[str], Optional[str]]] = None,
                   run: Runner = _run) -> Dict[str, str]:
    """For the doctor: whether hosts.conf matches the scheduler of this server. status: ok or warn."""
    queues = configuredQueues(path)
    scheduler = detectScheduler(which)
    if scheduler is None:
        if queues:
            return {"status": "warn", "detail": "Queues are set up, but this server has no scheduler commands: "
                                                "protocols sent to a queue will fail."}
        return {"status": "ok", "detail": "No scheduler: protocols run on this server."}
    if not queues:
        return {"status": "warn", "detail": f"{scheduler['name']} found but not set up: Settings → Host → Detect."}
    if scheduler["key"] not in SUPPORTED:
        return {"status": "ok", "detail": f"{scheduler['name']}: {len(queues)} queue(s) set up."}
    try:
        real = {queue["name"] for queue in _readAndBuild(scheduler["key"], "localhost", run)[0]}
    except Exception as exc:  # noqa: BLE001 - the scheduler's own message is what helps
        return {"status": "warn", "detail": f"{scheduler['name']}: its queues could not be read ({exc})."}
    missing = [name for name in queues if name not in real]
    if missing:
        return {"status": "warn", "detail": f"{scheduler['name']} has no queue {', '.join(missing)} any more: "
                                            "Settings → Host."}
    return {"status": "ok", "detail": f"{scheduler['name']}: {len(queues)} queue(s) set up, all found."}
