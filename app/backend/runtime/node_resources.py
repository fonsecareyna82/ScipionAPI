"""What a machine has in use right now: its processors, memory, disks and GPUs, and the processes on each GPU.

Each worker answers this for its own machine (report_node_resources). A process on a GPU comes with the processes
it descends from, so the server can tell which run it belongs to (a run records the worker process that ran it).
Nothing here may block for long: it runs on the worker's control channel.
"""
import logging
import os
import shutil
import socket
from typing import Any, Dict, List, Optional

from app.backend.runtime.gpu_sampler import MiB, TOOL, _number, _run, parseProcesses

logger = logging.getLogger(__name__)

# How far up from a process on a GPU its parents are followed
MAX_ANCESTORS = 40


def parentOf(pid: int, proc: str = "/proc") -> Optional[int]:
    try:
        with open(os.path.join(proc, str(pid), "stat")) as handle:
            stat = handle.read()
        return int(stat[stat.rindex(")") + 2:].split()[1])
    except (OSError, ValueError, IndexError):
        return None


def ancestorsOf(pid: int, proc: str = "/proc") -> List[int]:
    """The processes pid descends from, nearest first (none when it cannot be seen from here)."""
    chain: List[int] = []
    current = pid
    for _ in range(MAX_ANCESTORS):
        parent = parentOf(current, proc)
        if not parent or parent in chain or parent == current:
            break
        chain.append(parent)
        current = parent
    return chain


def parseGpuDetails(text: str) -> List[Dict[str, Any]]:
    """Lines of index, uuid, name, busy %, memory used and total (MiB), temperature."""
    gpus = []
    for line in text.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 7 or not parts[0]:
            continue
        temperature = _number(parts[6])
        gpus.append({"index": parts[0], "uuid": parts[1], "name": parts[2], "busy": _number(parts[3]),
                     "memoryUsedBytes": int(_number(parts[4]) * MiB),
                     "memoryTotalBytes": int(_number(parts[5]) * MiB),
                     "temperature": temperature if parts[6] not in ("", "[N/A]") else None})
    return gpus


def gpuSnapshot(tool: Optional[str] = None, proc: str = "/proc") -> Dict[str, Any]:
    tool = tool or shutil.which(TOOL)
    if not tool:
        return {"gpus": [], "gpuError": None}
    details = _run([tool, "--query-gpu=index,uuid,name,utilization.gpu,memory.used,memory.total,temperature.gpu",
                    "--format=csv,noheader,nounits"])
    if details is None:
        return {"gpus": [], "gpuError": "The GPUs could not be read"}
    gpus = parseGpuDetails(details)
    processes = parseProcesses(_run([tool, "--query-compute-apps=gpu_uuid,pid,used_memory",
                                     "--format=csv,noheader,nounits"]) or "")
    for gpu in gpus:
        gpu["processes"] = [{"pid": process.pid, "memoryBytes": process.memoryBytes,
                             "ancestors": ancestorsOf(process.pid, proc)}
                            for process in processes if process.uuid == gpu["uuid"]]
    return {"gpus": gpus, "gpuError": None}


def memoryOf(meminfo: str = "/proc/meminfo") -> Dict[str, Optional[int]]:
    values: Dict[str, int] = {}
    try:
        with open(meminfo) as handle:
            for line in handle:
                name, _, rest = line.partition(":")
                parts = rest.split()
                if parts and parts[0].isdigit():
                    values[name.strip()] = int(parts[0]) * 1024
    except OSError:
        pass
    return {"memoryTotalBytes": values.get("MemTotal"), "memoryAvailableBytes": values.get("MemAvailable")}


def diskOf(label: str, path: Optional[str]) -> Optional[Dict[str, Any]]:
    if not path:
        return None
    try:
        usage = shutil.disk_usage(path)
    except OSError:
        return None
    return {"label": label, "path": str(path), "totalBytes": usage.total, "freeBytes": usage.free}


def _projectsFolder() -> Optional[str]:
    try:
        from app.backend.api.services.project_storage import projectsRoot

        return str(projectsRoot())
    except Exception:
        return None


def _scratchFolder() -> Optional[str]:
    try:
        from app.backend.api.services.scratch_settings import scratchStatus

        status = scratchStatus()
        return status.get("path") if status.get("exists") else None
    except Exception:
        return None


def machineSnapshot() -> Dict[str, Any]:
    """This machine now."""
    try:
        load = os.getloadavg()
    except OSError:
        load = (None, None, None)
    disks = [disk for disk in (diskOf("projects", _projectsFolder()), diskOf("scratch", _scratchFolder())) if disk]
    snapshot = {"hostname": socket.gethostname(), "cpuCount": os.cpu_count(), "load1": load[0], "load5": load[1],
                "disks": disks}
    snapshot.update(memoryOf())
    try:
        snapshot.update(gpuSnapshot())
    except Exception as error:
        logger.warning("Could not read the GPUs", exc_info=True)
        snapshot.update({"gpus": [], "gpuError": str(error)})
    return snapshot
