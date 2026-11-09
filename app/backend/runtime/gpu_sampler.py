"""How much a run really uses the GPUs it was given.

While the run goes on, a thread looks at its GPUs every few seconds through the driver's command line tool:

- a GPU counts as busy as the tool says only while one of the run's processes (the worker and what it started)
  is on it; a GPU the run was given but does not touch counts as idle;
- the memory is what the run's processes hold on its GPUs, added up.

When the tool lists processes this machine cannot see (a container with its own process numbers), the run's
processes cannot be told apart and the GPU's own figures are taken. A machine without the tool is never looked at.
"""
import logging
import os
import shutil
import subprocess
import threading
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Set

logger = logging.getLogger(__name__)

DEFAULT_INTERVAL_SECONDS = 15.0
TOOL = "nvidia-smi"
TOOL_TIMEOUT_SECONDS = 10.0
MiB = 1024 * 1024


def intervalSeconds() -> float:
    try:
        value = float(os.environ.get("SCIPIONWEB_GPU_SAMPLE_SECONDS", DEFAULT_INTERVAL_SECONDS))
    except ValueError:
        value = DEFAULT_INTERVAL_SECONDS
    return max(2.0, value)


@dataclass
class GpuState:
    index: str
    uuid: str
    busy: float
    memoryBytes: int


@dataclass
class GpuProcess:
    uuid: str
    pid: int
    memoryBytes: int


@dataclass
class GpuUse:
    """What the looks found so far."""
    samples: int = 0
    busySum: float = 0.0
    memoryPeakBytes: Optional[int] = None

    def add(self, busy: float, memoryBytes: int) -> None:
        self.samples += 1
        self.busySum += busy
        self.memoryPeakBytes = max(self.memoryPeakBytes or 0, memoryBytes)


def _number(text: str) -> float:
    try:
        return float(text.strip())
    except ValueError:
        return 0.0


def parseGpus(text: str) -> List[GpuState]:
    """Lines of index, uuid, busy %, memory used (MiB)."""
    gpus = []
    for line in text.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 4 or not parts[0]:
            continue
        gpus.append(GpuState(parts[0], parts[1], _number(parts[2]), int(_number(parts[3]) * MiB)))
    return gpus


def parseProcesses(text: str) -> List[GpuProcess]:
    """Lines of GPU uuid, process id, memory used (MiB)."""
    processes = []
    for line in text.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 3 or not parts[1].isdigit():
            continue
        processes.append(GpuProcess(parts[0], int(parts[1]), int(_number(parts[2]) * MiB)))
    return processes


def physicalGpus(gpuIds: Iterable[str], visible: Optional[str]) -> List[str]:
    """The machine's GPUs (index or uuid) behind the ids a run was given: a run numbers the GPUs the worker sees,
    so with a list of visible devices its ids point into that list."""
    ids = [str(gpu).strip() for gpu in gpuIds if str(gpu).strip()]
    devices = [device.strip() for device in (visible or "").split(",") if device.strip()]
    if not devices:
        return ids
    physical = []
    for gpu in ids:
        if gpu.isdigit() and int(gpu) < len(devices):
            physical.append(devices[int(gpu)])
        else:
            physical.append(gpu)
    return physical


def processTree(root: int, proc: str = "/proc") -> Set[int]:
    """root and every process descending from it."""
    children: Dict[int, List[int]] = {}
    try:
        names = os.listdir(proc)
    except OSError:
        return {root}
    for name in names:
        if not name.isdigit():
            continue
        try:
            with open(os.path.join(proc, name, "stat")) as handle:
                stat = handle.read()
            # The command name is between parentheses and may hold spaces
            parent = int(stat[stat.rindex(")") + 2:].split()[1])
        except (OSError, ValueError, IndexError):
            continue
        children.setdefault(parent, []).append(int(name))
    tree, pending = set(), [root]
    while pending:
        pid = pending.pop()
        if pid in tree:
            continue
        tree.add(pid)
        pending.extend(children.get(pid, []))
    return tree


def measure(gpus: List[GpuState], processes: List[GpuProcess], wanted: List[str], tree: Set[int],
            visiblePids: Set[int]) -> Optional[tuple]:
    """One look: the mean busy % of the wanted GPUs and the memory the run holds on them; None when none of the
    wanted GPUs is found."""
    found = [gpu for gpu in gpus if gpu.index in wanted or gpu.uuid in wanted]
    if not found:
        return None
    busy, memory = [], 0
    for gpu in found:
        onGpu = [process for process in processes if process.uuid == gpu.uuid]
        if onGpu and not any(process.pid in visiblePids for process in onGpu):
            # Processes of another namespace: the GPU's own figures
            busy.append(gpu.busy)
            memory += gpu.memoryBytes
            continue
        mine = [process for process in onGpu if process.pid in tree]
        busy.append(gpu.busy if mine else 0.0)
        memory += sum(process.memoryBytes for process in mine)
    return sum(busy) / len(busy), memory


def _run(arguments: List[str]) -> Optional[str]:
    try:
        result = subprocess.run(arguments, capture_output=True, text=True, timeout=TOOL_TIMEOUT_SECONDS)
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout if result.returncode == 0 else None


class GpuSampler:
    """Looks at a run's GPUs from a thread until stopped; use holds what it found."""

    def __init__(self, gpuIds: Iterable[str], root: Optional[int] = None, interval: Optional[float] = None,
                 tool: Optional[str] = None):
        self.wanted = physicalGpus(gpuIds, os.environ.get("CUDA_VISIBLE_DEVICES"))
        self.root = root or os.getpid()
        self.interval = interval or intervalSeconds()
        self.tool = tool or shutil.which(TOOL)
        self.use = GpuUse()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    @classmethod
    def startFor(cls, gpuIds: Iterable[str]) -> Optional["GpuSampler"]:
        sampler = cls(gpuIds)
        if not sampler.wanted or not sampler.tool:
            return None
        sampler.start()
        return sampler

    def sampleOnce(self) -> None:
        gpus = _run([self.tool, "--query-gpu=index,uuid,utilization.gpu,memory.used",
                     "--format=csv,noheader,nounits"])
        if gpus is None:
            return
        processes = _run([self.tool, "--query-compute-apps=gpu_uuid,pid,used_memory",
                          "--format=csv,noheader,nounits"]) or ""
        tree = processTree(self.root)
        listed = parseProcesses(processes)
        visible = {process.pid for process in listed if os.path.exists(f"/proc/{process.pid}")}
        found = measure(parseGpus(gpus), listed, self.wanted, tree, visible)
        if found is not None:
            with self._lock:
                self.use.add(*found)

    def snapshot(self) -> GpuUse:
        with self._lock:
            return GpuUse(self.use.samples, self.use.busySum, self.use.memoryPeakBytes)

    def _loop(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                self.sampleOnce()
            except Exception:
                logger.debug("Could not look at the GPUs", exc_info=True)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="gpu-sampler", daemon=True)
        self._thread.start()

    def stop(self) -> GpuUse:
        self._stop.set()
        return self.snapshot()
